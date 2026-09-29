//! Cross-check the hand-written constants against the kernel UAPI headers via the
//! `linux-raw-sys` crate. Syscall numbers are not covered (the crate exposes no
//! `__NR_*`); they are checked structurally by the other tests exercising real
//! syscalls (server.rs, clone_asm.rs).

use linux_raw_sys::{errno as e, general as g, net as n};
use rsyscall_core::sys::consts as c;

/// Both sides are non-negative, so comparing as `u64` is exact (linux-raw-sys
/// constants are `u32`; ours are `i64`).
macro_rules! same {
    ($mine:expr, $theirs:expr) => {
        assert_eq!($mine as u64, $theirs as u64, concat!(stringify!($mine), " != ", stringify!($theirs)));
    };
}

#[test]
fn flags_and_errnos_match_linux_raw_sys() {
    // clone flags
    same!(c::CLONE_VM, g::CLONE_VM);
    same!(c::CLONE_FS, g::CLONE_FS);
    same!(c::CLONE_FILES, g::CLONE_FILES);
    same!(c::CLONE_SIGHAND, g::CLONE_SIGHAND);
    same!(c::CLONE_PARENT, g::CLONE_PARENT);
    same!(c::CLONE_CHILD_CLEARTID, g::CLONE_CHILD_CLEARTID);

    // futex / open
    same!(c::FUTEX_WAIT, g::FUTEX_WAIT);
    same!(c::O_CLOEXEC, g::O_CLOEXEC);
    same!(c::O_PATH, g::O_PATH);
    // SOCK_CLOEXEC shares O_CLOEXEC's numeric value on Linux.
    same!(c::SOCK_CLOEXEC, g::O_CLOEXEC);

    // signals
    same!(c::SIGCHLD, g::SIGCHLD);
    same!(c::SIGSTOP, g::SIGSTOP);
    same!(c::SIG_BLOCK, g::SIG_BLOCK);
    same!(c::SIG_UNBLOCK, g::SIG_UNBLOCK);

    // socket / message flags
    same!(c::AF_UNIX, n::AF_UNIX);
    same!(c::SOCK_STREAM, n::SOCK_STREAM);
    same!(c::MSG_WAITALL, n::MSG_WAITALL);
    same!(c::MSG_NOSIGNAL, n::MSG_NOSIGNAL);
    same!(c::MSG_CMSG_CLOEXEC, n::MSG_CMSG_CLOEXEC);
    same!(c::MSG_CTRUNC, n::MSG_CTRUNC);
    same!(c::SOL_SOCKET, n::SOL_SOCKET);
    same!(c::SCM_RIGHTS, n::SCM_RIGHTS);
    same!(c::SHUT_RDWR, n::SHUT_RDWR);

    // errnos
    same!(c::EINTR, e::EINTR);
    same!(c::EAGAIN, e::EAGAIN);
    same!(c::EPIPE, e::EPIPE);
    same!(c::ENOTSOCK, e::ENOTSOCK);
    same!(c::ECONNABORTED, e::ECONNABORTED);
}
