//! `rsyscall-bootstrap` — the ssh bootstrap (bootstrap-handshakes.md §2, §6).
//!
//! `bootstrap socket` (cwd = the temporary directory): listen on `data` and on the
//! hand-off socket `pass`, print `done\n`, hand the `data` listening socket to the
//! `rsyscall`-mode process over `pass`, exit 0.
//! `bootstrap rsyscall`: take the listening socket over `pass`, accept the syscall
//! socket then the data socket, write the describe struct and the environment on
//! the data socket, then serve on the syscall socket.
#![no_std]
#![no_main]

#[path = "../rt/mem.rs"]
mod mem;
#[path = "../rt/panic.rs"]
mod panic;
#[path = "../rt/start.rs"]
mod start;
#[path = "../rt/exports.rs"]
mod exports;

use core::ffi::c_void;
use core::ptr::null_mut;
use rsyscall_core::cmsg::{self, RecvFdsError, MAX_FDS};
use rsyscall_core::cstr;
use rsyscall_core::describe::{self, Bootstrap, Plain};
use rsyscall_core::diag::{diag, diag2};
use rsyscall_core::io::write_all;
use rsyscall_core::sys::{self, consts::*, SockaddrUn};

const DEFAULT_PROG: &[u8] = b"rsyscall-bootstrap";

fn main(argc: usize, argv: *const *const u8, envp: *const *const u8) -> i32 {
    // SAFETY: argv/envp are the kernel-provided arrays (rt/start.rs).
    let prog = if argc >= 1 { cstr::basename(unsafe { cstr::cstr(*argv) }) } else { DEFAULT_PROG };
    if argc < 2 {
        // §6 (observed): `rsyscall-bootstrap: usage: <path> <type>`.
        diag(prog, b"usage: <path> <type>", None);
        return 1;
    }
    let mode = unsafe { cstr::cstr(*argv.add(1)) };
    if mode == b"socket" {
        socket_mode(prog)
    } else if mode == b"rsyscall" {
        rsyscall_mode(prog, envp)
    } else {
        diag2(prog, b"unknown type ", mode, None);
        1
    }
}

/// An `AF_UNIX` `SOCK_STREAM` socket bound to `name` in the cwd and listening.
fn listen_on(prog: &[u8], name: &[u8]) -> Result<i32, ()> {
    let fd = sys::socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if fd < 0 {
        diag(prog, b"socket", Some(-fd));
        return Err(());
    }
    let fd = fd as i32;
    let Some((addr, len)) = SockaddrUn::from_path(name) else {
        return Err(());
    };
    let r = sys::bind(fd, &addr as *const SockaddrUn as *const c_void, len as i64);
    if r < 0 {
        diag(prog, b"bind", Some(-r)); // §6 (observed): `bind: <errno text>`
        return Err(());
    }
    let r = sys::listen(fd, 10);
    if r < 0 {
        diag(prog, b"listen", Some(-r));
        return Err(());
    }
    Ok(fd)
}

fn accept_one(prog: &[u8], listening: i32, what: &[u8]) -> Result<i32, ()> {
    loop {
        let r = sys::accept4(listening, null_mut(), null_mut(), SOCK_CLOEXEC);
        if r >= 0 {
            return Ok(r as i32);
        }
        if r == -EINTR || r == -ECONNABORTED {
            continue;
        }
        diag(prog, what, Some(-r));
        return Err(());
    }
}

/// Stage 1 (§2): `data` and `pass` listening before `done\n`; then hand `data` over.
fn socket_mode(prog: &[u8]) -> i32 {
    let Ok(data) = listen_on(prog, b"data") else { return 1 };
    let Ok(pass) = listen_on(prog, b"pass") else { return 1 };
    if write_all(1, b"done\n").is_err() {
        diag(prog, b"write(stdout)", None);
        return 1;
    }
    // Nothing more may reach stdout from here on (§2).
    let Ok(conn) = accept_one(prog, pass, b"accept(pass)") else { return 1 };
    // The hand-off file is removed once the connection exists (§2 Recommended default).
    let _ = sys::unlink(b"pass\0".as_ptr());
    let r = cmsg::send_fds(conn, &[data]);
    if r < 0 {
        diag(prog, b"sendmsg(pass)", Some(-r));
        return 1;
    }
    let _ = sys::close(conn);
    0
}

/// Stage 3 (§2): obtain the listening socket, accept twice, describe, serve.
fn rsyscall_mode(prog: &[u8], envp: *const *const u8) -> i32 {
    let sock = sys::socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if sock < 0 {
        diag(prog, b"socket", Some(-sock));
        return 1;
    }
    let sock = sock as i32;
    let Some((addr, len)) = SockaddrUn::from_path(b"pass") else { return 1 };
    let r = sys::connect(sock, &addr as *const SockaddrUn as *const c_void, len as i64);
    if r < 0 {
        diag(prog, b"connect(pass)", Some(-r));
        return 1;
    }
    let mut fds = [0i32; MAX_FDS];
    let listening = match cmsg::recv_fds(sock, &mut fds) {
        Ok(1) => fds[0],
        Ok(_) => {
            diag(prog, b"recvmsg(pass): expected 1 file descriptor", None);
            return 1;
        }
        Err(RecvFdsError::Errno(e)) => {
            diag(prog, b"recvmsg(pass)", Some(e));
            return 1;
        }
        Err(RecvFdsError::Eof) => {
            diag(prog, b"recvmsg(pass): unexpected EOF", None);
            return 1;
        }
        Err(RecvFdsError::Malformed) => {
            diag(prog, b"recvmsg(pass): malformed file-descriptor message", None);
            return 1;
        }
    };

    // Exactly two connections, in order: the syscall socket, then the data socket.
    let Ok(syscall_sock) = accept_one(prog, listening, b"accept(data)") else { return 1 };
    let Ok(data_sock) = accept_one(prog, listening, b"accept(data)") else { return 1 };
    // The hand-off is complete: the pass connection is not needed any more. Closed
    // only now so the accepted sockets keep the numbers they were created with.
    let _ = sys::close(sock);

    let desc = Bootstrap {
        symbols: exports::symbol_table(),
        pid: sys::getpid() as i32,
        listening_sock: listening,
        syscall_sock,
        data_sock,
        // SAFETY: envp is the kernel-provided array.
        envp_count: unsafe { cstr::count_env(envp) } as u64,
    };
    // The describe must be complete before blocking on the syscall socket (§2).
    if write_all(data_sock, desc.as_bytes()).is_err() || unsafe { describe::write_env(data_sock, envp) }.is_err() {
        diag(prog, b"write(data_sock)", None);
        return 1;
    }
    // listening_sock and data_sock stay open and unused from here on (§2);
    // fds 0/1/2 are untouched. 0 on EOF (§6 Recommended default).
    exports::rsyscall_server(syscall_sock, syscall_sock)
}
