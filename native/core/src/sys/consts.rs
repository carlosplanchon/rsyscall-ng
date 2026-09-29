//! Hand-written kernel constants for x86-64 (native-abi.md §1).
//!
//! Every value carries a `// source:` note. Flags and errnos are cross-checked
//! against the `linux-raw-sys` crate in `tests/consts.rs`; x86-64 syscall numbers
//! are not present in that crate (it exposes no `__NR_*`), so they are cited to the
//! syscalls the spec requires the server/helpers to issue and are the stable public
//! kernel ABI for this architecture.
//!
//! All values are `i64` so they can be passed straight to `raw_syscall7`; they are
//! non-negative, so the `as u64` comparison in the cross-check is exact.

// ---- x86-64 syscall numbers ------------------------------------------------
// source: x86-64 public syscall ABI; the specific calls are those the server and
// helpers must issue per wire-protocol.md §3/§5/§6 and native-abi.md §3/§5/§6.
pub const SYS_READ: i64 = 0;
pub const SYS_WRITE: i64 = 1;
pub const SYS_CLOSE: i64 = 3;
pub const SYS_MMAP: i64 = 9;
pub const SYS_RT_SIGPROCMASK: i64 = 14;
pub const SYS_GETPID: i64 = 39;
pub const SYS_SOCKET: i64 = 41;
pub const SYS_CONNECT: i64 = 42;
pub const SYS_SENDTO: i64 = 44;
pub const SYS_RECVFROM: i64 = 45;
pub const SYS_SENDMSG: i64 = 46;
pub const SYS_RECVMSG: i64 = 47;
pub const SYS_SHUTDOWN: i64 = 48;
pub const SYS_BIND: i64 = 49;
pub const SYS_LISTEN: i64 = 50;
pub const SYS_CLONE: i64 = 56;
pub const SYS_EXIT: i64 = 60;
pub const SYS_KILL: i64 = 62;
pub const SYS_UNLINK: i64 = 87;
pub const SYS_PRCTL: i64 = 157;
pub const SYS_GETTID: i64 = 186;
pub const SYS_TKILL: i64 = 200;
pub const SYS_FUTEX: i64 = 202;
pub const SYS_EXIT_GROUP: i64 = 231;
pub const SYS_OPENAT: i64 = 257;
pub const SYS_ACCEPT4: i64 = 288;

// ---- socket / message flags ------------------------------------------------
// source: wire-protocol.md §5 (MSG_WAITALL in request_memory_write) and §10
// (MSG_NOSIGNAL); bootstrap-handshakes.md §0 (MSG_CMSG_CLOEXEC, MSG_CTRUNC,
// SOL_SOCKET, SCM_RIGHTS, AF_UNIX); vectors/v0.json scm_rights_* / describe_stub.
pub const MSG_WAITALL: i64 = 0x100;
pub const MSG_NOSIGNAL: i64 = 0x4000;
pub const MSG_CMSG_CLOEXEC: i64 = 0x40000000;
pub const MSG_CTRUNC: i64 = 0x8;
pub const SOL_SOCKET: i64 = 1;
pub const SCM_RIGHTS: i64 = 1;
pub const AF_UNIX: i64 = 1;
pub const SOCK_STREAM: i64 = 1;
pub const SOCK_CLOEXEC: i64 = 0x80000; // == O_CLOEXEC
pub const SHUT_RDWR: i64 = 2;

// ---- futex -----------------------------------------------------------------
// source: native-abi.md §3.4 (FUTEX_WAIT, no FUTEX_PRIVATE_FLAG).
pub const FUTEX_WAIT: i64 = 0;

// ---- signals ---------------------------------------------------------------
// source: native-abi.md §3.4 (SIGSTOP), §9 / bootstrap-handshakes.md §4 (SIGCHLD),
// §4 (SIG_BLOCK/SIG_UNBLOCK for the client's rt_sigprocmask).
pub const SIGCHLD: i64 = 17;
pub const SIGSTOP: i64 = 19;
pub const SIG_BLOCK: i64 = 0;
pub const SIG_UNBLOCK: i64 = 1;

// ---- open flags ------------------------------------------------------------
// source: bootstrap-handshakes.md §4 (O_PATH long-path workaround; O_CLOEXEC).
pub const O_CLOEXEC: i64 = 0x80000;
pub const O_PATH: i64 = 0x200000;

// ---- errnos ----------------------------------------------------------------
// source: wire-protocol.md §3/§4 (EINTR), §10 (EPIPE for SIGPIPE handling);
// native-abi.md §3.4 (EAGAIN); bootstrap-handshakes.md §6 (ENOTSOCK),
// §5 (ECONNABORTED). Values are the x86-64 UAPI errno numbers.
pub const EINTR: i64 = 4;
pub const EAGAIN: i64 = 11;
pub const EPIPE: i64 = 32;
pub const ENOTSOCK: i64 = 88;
pub const ECONNABORTED: i64 = 103;

// ---- clone flags -----------------------------------------------------------
// source: vectors/v0.json clone_args.constants; native-abi.md §5.
pub const CLONE_VM: i64 = 0x100;
pub const CLONE_FS: i64 = 0x200;
pub const CLONE_FILES: i64 = 0x400;
pub const CLONE_SIGHAND: i64 = 0x800;
pub const CLONE_PARENT: i64 = 0x8000;
pub const CLONE_CHILD_CLEARTID: i64 = 0x200000;
