//! `rsyscall-stdin-bootstrap` (bootstrap-handshakes.md §3, §6).
//!
//! fd 0 is one end of a client `socketpair`: receive exactly one SCM_RIGHTS
//! message carrying the syscall socket, the data socket and the connection fd,
//! write the describe struct and the environment on the data socket, then serve on
//! the syscall socket. fd 0 stays open as fd 0 and is never read again; extra
//! arguments are ignored (§3 Recommended default).
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

use rsyscall_core::cmsg::{self, RecvFdsError, MAX_FDS};
use rsyscall_core::cstr;
use rsyscall_core::describe::{self, Plain, StdinBootstrap};
use rsyscall_core::diag::diag;
use rsyscall_core::io::write_all;
use rsyscall_core::sys;

const DEFAULT_PROG: &[u8] = b"rsyscall-stdin-bootstrap";

fn main(argc: usize, argv: *const *const u8, envp: *const *const u8) -> i32 {
    // SAFETY: argv/envp are the kernel-provided arrays (rt/start.rs).
    let prog = if argc >= 1 { cstr::basename(unsafe { cstr::cstr(*argv) }) } else { DEFAULT_PROG };

    // §3: exactly one message on fd 0 with, in order, syscall socket, data socket,
    // connection fd. §6 (observed): `recvmsg(sock=0): Socket operation on non-socket`.
    let mut fds = [0i32; MAX_FDS];
    let n = match cmsg::recv_fds(0, &mut fds) {
        Ok(n) => n,
        Err(RecvFdsError::Errno(e)) => {
            diag(prog, b"recvmsg(sock=0)", Some(e));
            return 1;
        }
        Err(RecvFdsError::Eof) => {
            diag(prog, b"recvmsg(sock=0): unexpected EOF", None);
            return 1;
        }
        Err(RecvFdsError::Malformed) => {
            diag(prog, b"recvmsg(sock=0): malformed file-descriptor message", None);
            return 1;
        }
    };
    if n != 3 {
        diag(prog, b"recvmsg(sock=0): expected 3 file descriptors", None);
        return 1;
    }
    let (syscall_fd, data_fd, connecting_fd) = (fds[0], fds[1], fds[2]);

    let desc = StdinBootstrap {
        symbols: exports::symbol_table(),
        pid: sys::getpid() as i32,
        syscall_fd,
        data_fd,
        futex_memfd: -1, // §3: Unspecified in v0; Recommended default -1
        connecting_fd,
        _pad: 0,
        // SAFETY: envp is the kernel-provided array.
        envp_count: unsafe { cstr::count_env(envp) } as u64,
    };
    // The describe must be complete before blocking on the syscall socket (§3).
    if write_all(data_fd, desc.as_bytes()).is_err() || unsafe { describe::write_env(data_fd, envp) }.is_err() {
        diag(prog, b"write(data_fd)", None);
        return 1;
    }
    // data_fd and connecting_fd stay open and untouched; fds 0/1/2 as inherited;
    // the signal mask is left alone (§3). 0 on EOF (§6 Recommended default).
    exports::rsyscall_server(syscall_fd, syscall_fd)
}
