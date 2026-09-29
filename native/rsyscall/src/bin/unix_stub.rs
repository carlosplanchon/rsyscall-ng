//! `rsyscall-unix-stub` (bootstrap-handshakes.md §4, §6).
//!
//! Connect to the socket path in `RSYSCALL_UNIX_STUB_SOCK_PATH`, receive exactly
//! one SCM_RIGHTS message carrying the syscall socket, the data socket, a memfd
//! and the connection fd, write the describe struct, all `argc` arguments and the
//! environment on the data socket, then serve on the syscall socket.
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
use core::ptr::{null, null_mut};
use rsyscall_core::cmsg::{self, RecvFdsError, MAX_FDS};
use rsyscall_core::cstr;
use rsyscall_core::describe::{self, Plain, UnixStub};
use rsyscall_core::diag::{diag, diag3};
use rsyscall_core::io::write_all;
use rsyscall_core::sys::{self, consts::*, SockaddrUn};

const DEFAULT_PROG: &[u8] = b"rsyscall-unix-stub";
const VAR: &[u8] = b"RSYSCALL_UNIX_STUB_SOCK_PATH=";
/// `sigmask` bit for SIGCHLD: bit `n-1` for signal `n` (§4).
const SIGCHLD_BIT: u64 = 1u64 << (SIGCHLD - 1);

/// Connect `sock` to `path`. Paths of up to 107 bytes use a `sockaddr_un`
/// directly (§4: they MUST work); longer paths are Unspecified in v0 and take the
/// Recommended default: open with `O_PATH|O_CLOEXEC` and connect to
/// `/proc/self/fd/<n>`. Returns the `connect` result and the O_PATH fd, which the
/// caller closes after the handshake.
fn connect_path(sock: i32, path: &[u8]) -> (i64, Option<i32>) {
    if let Some((addr, len)) = SockaddrUn::from_path(path) {
        return (sys::connect(sock, &addr as *const SockaddrUn as *const c_void, len as i64), None);
    }
    // `path` is the tail of an envp entry, so the byte after it is that entry's NUL
    // terminator: it is usable as a C string as is.
    let pfd = sys::openat(AT_FDCWD as i32, path.as_ptr(), O_PATH | O_CLOEXEC, 0);
    if pfd < 0 {
        return (pfd, None);
    }
    let pfd = pfd as i32;
    const PREFIX: &[u8] = b"/proc/self/fd/";
    let mut proc_path = [0u8; 34]; // prefix (14) + up to 20 digits
    let mut i = 0;
    while i < PREFIX.len() {
        proc_path[i] = PREFIX[i];
        i += 1;
    }
    let mut d = [0u8; 20];
    let digits = cstr::fmt_decimal(pfd as u64, &mut d);
    let mut j = 0;
    while j < digits.len() {
        proc_path[i + j] = digits[j];
        j += 1;
    }
    let n = i + digits.len();
    match SockaddrUn::from_path(&proc_path[..n]) {
        Some((addr, len)) => {
            (sys::connect(sock, &addr as *const SockaddrUn as *const c_void, len as i64), Some(pfd))
        }
        None => (-ENAMETOOLONG, Some(pfd)), // unreachable: 34 < 107
    }
}

fn main(argc: usize, argv: *const *const u8, envp: *const *const u8) -> i32 {
    // SAFETY: argv/envp are the kernel-provided arrays (rt/start.rs).
    let prog = if argc >= 1 { cstr::basename(unsafe { cstr::cstr(*argv) }) } else { DEFAULT_PROG };

    let Some(path) = (unsafe { cstr::env_lookup(envp, VAR) }) else {
        diag(prog, b"missing environment variable RSYSCALL_UNIX_STUB_SOCK_PATH", None);
        return 1;
    };

    let sock = sys::socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if sock < 0 {
        diag(prog, b"socket", Some(-sock));
        return 1;
    }
    let sock = sock as i32;
    let (r, opath_fd) = connect_path(sock, path);
    if r < 0 {
        diag3(prog, b"connect(", path, b")", Some(-r));
        return 1;
    }

    // §4: exactly one message with, in order, syscall socket, data socket, memfd,
    // connection fd.
    let mut fds = [0i32; MAX_FDS];
    let n = match cmsg::recv_fds(sock, &mut fds) {
        Ok(n) => n,
        Err(RecvFdsError::Errno(e)) => {
            diag(prog, b"recvmsg", Some(e));
            return 1;
        }
        Err(RecvFdsError::Eof) => {
            diag(prog, b"recvmsg: unexpected EOF", None);
            return 1;
        }
        Err(RecvFdsError::Malformed) => {
            diag(prog, b"recvmsg: malformed file-descriptor message", None);
            return 1;
        }
    };
    if n != 4 {
        diag(prog, b"recvmsg: expected 4 file descriptors", None);
        return 1;
    }
    let (syscall_fd, data_fd, futex_memfd, connecting_fd) = (fds[0], fds[1], fds[2], fds[3]);
    // The handshake is done: the O_PATH fd (if any) and our end of the connection
    // are not needed any more (§4 Recommended default: close the connection).
    if let Some(pfd) = opath_fd {
        let _ = sys::close(pfd);
    }
    let _ = sys::close(sock);

    // §4 "Signal mask": report the blocked set; it MUST NOT include SIGCHLD, and a
    // SIGCHLD inherited as blocked MUST be unblocked before serving.
    let mut sigmask: u64 = 0;
    let r = sys::rt_sigprocmask(SIG_BLOCK, null(), &mut sigmask as *mut u64, 8);
    if r < 0 {
        diag(prog, b"rt_sigprocmask", Some(-r));
        return 1;
    }
    if sigmask & SIGCHLD_BIT != 0 {
        let set: u64 = SIGCHLD_BIT;
        let r = sys::rt_sigprocmask(SIG_UNBLOCK, &set as *const u64, null_mut(), 8);
        if r < 0 {
            diag(prog, b"rt_sigprocmask(SIG_UNBLOCK)", Some(-r));
            return 1;
        }
        sigmask &= !SIGCHLD_BIT;
    }

    let desc = UnixStub {
        symbols: exports::symbol_table(),
        pid: sys::getpid() as i32,
        syscall_fd,
        data_fd,
        futex_memfd,
        connecting_fd,
        _pad: 0,
        argc: argc as u64,
        // SAFETY: envp is the kernel-provided array.
        envp_count: unsafe { cstr::count_env(envp) } as u64,
        sigmask,
    };
    // The describe, then ALL argc arguments (argv[0] included, empty strings
    // verbatim), then the environment (RSYSCALL_UNIX_STUB_SOCK_PATH not stripped),
    // all complete before blocking on the syscall socket (§4).
    if write_all(data_fd, desc.as_bytes()).is_err() {
        diag(prog, b"write(data_fd)", None);
        return 1;
    }
    let mut i = 0;
    while i < argc {
        // SAFETY: i < argc, so argv[i] is a valid C string.
        let a = unsafe { cstr::cstr(*argv.add(i)) };
        if describe::write_lp_string(data_fd, a).is_err() {
            diag(prog, b"write(data_fd)", None);
            return 1;
        }
        i += 1;
    }
    if unsafe { describe::write_env(data_fd, envp) }.is_err() {
        diag(prog, b"write(data_fd)", None);
        return 1;
    }
    // data_fd, futex_memfd and connecting_fd stay open and untouched; fds 0/1/2 as
    // inherited (§4). 0 on EOF (§6 Recommended default).
    exports::rsyscall_server(syscall_fd, syscall_fd)
}
