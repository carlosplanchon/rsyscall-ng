//! Thin wrappers over `raw_syscall7` and the `#[repr(C)]` ABI structs
//! (native-abi.md §3; layouts from abi-layouts.generated.md).
//!
//! Internal callers use `raw_syscall7` directly (never the exported
//! `rsyscall_raw_syscall`), so a client interposing the exported symbol cannot
//! divert the server's own syscalls (native-abi.md §9).

pub mod consts;

use crate::arch::x86_64::raw_syscall7;
use consts::*;
use core::ffi::c_void;

#[inline]
fn addr<T>(p: *const T) -> i64 {
    p as usize as i64
}

// ---- syscall wrappers ------------------------------------------------------
// Each passes its arguments verbatim and returns the raw kernel value (a negative
// -errno on failure); no errno translation (wire-protocol.md §4).

#[inline]
pub fn read(fd: i32, buf: *mut u8, count: usize) -> i64 {
    raw_syscall7(fd as i64, addr(buf), count as i64, 0, 0, 0, SYS_READ)
}

#[inline]
pub fn write(fd: i32, buf: *const u8, count: usize) -> i64 {
    raw_syscall7(fd as i64, addr(buf), count as i64, 0, 0, 0, SYS_WRITE)
}

#[inline]
pub fn sendto(
    fd: i32,
    buf: *const u8,
    len: usize,
    flags: i64,
    addr_ptr: *const c_void,
    addrlen: i64,
) -> i64 {
    raw_syscall7(fd as i64, addr(buf), len as i64, flags, addr(addr_ptr), addrlen, SYS_SENDTO)
}

#[inline]
pub fn recvfrom(
    fd: i32,
    buf: *mut u8,
    len: usize,
    flags: i64,
    addr_ptr: *mut c_void,
    addrlen: *mut u32,
) -> i64 {
    raw_syscall7(fd as i64, addr(buf), len as i64, flags, addr(addr_ptr), addr(addrlen), SYS_RECVFROM)
}

#[inline]
pub fn recvmsg(fd: i32, msg: *mut Msghdr, flags: i64) -> i64 {
    raw_syscall7(fd as i64, addr(msg), flags, 0, 0, 0, SYS_RECVMSG)
}

#[inline]
pub fn sendmsg(fd: i32, msg: *const Msghdr, flags: i64) -> i64 {
    raw_syscall7(fd as i64, addr(msg), flags, 0, 0, 0, SYS_SENDMSG)
}

#[inline]
pub fn accept4(fd: i32, addr_ptr: *mut c_void, addrlen: *mut u32, flags: i64) -> i64 {
    raw_syscall7(fd as i64, addr(addr_ptr), addr(addrlen), flags, 0, 0, SYS_ACCEPT4)
}

#[inline]
pub fn shutdown(fd: i32, how: i64) -> i64 {
    raw_syscall7(fd as i64, how, 0, 0, 0, 0, SYS_SHUTDOWN)
}

#[inline]
pub fn close(fd: i32) -> i64 {
    raw_syscall7(fd as i64, 0, 0, 0, 0, 0, SYS_CLOSE)
}

#[inline]
pub fn socket(domain: i64, ty: i64, protocol: i64) -> i64 {
    raw_syscall7(domain, ty, protocol, 0, 0, 0, SYS_SOCKET)
}

#[inline]
pub fn bind(fd: i32, addr_ptr: *const c_void, addrlen: i64) -> i64 {
    raw_syscall7(fd as i64, addr(addr_ptr), addrlen, 0, 0, 0, SYS_BIND)
}

#[inline]
pub fn listen(fd: i32, backlog: i64) -> i64 {
    raw_syscall7(fd as i64, backlog, 0, 0, 0, 0, SYS_LISTEN)
}

#[inline]
pub fn connect(fd: i32, addr_ptr: *const c_void, addrlen: i64) -> i64 {
    raw_syscall7(fd as i64, addr(addr_ptr), addrlen, 0, 0, 0, SYS_CONNECT)
}

#[inline]
pub fn getpid() -> i64 {
    raw_syscall7(0, 0, 0, 0, 0, 0, SYS_GETPID)
}

#[inline]
pub fn gettid() -> i64 {
    raw_syscall7(0, 0, 0, 0, 0, 0, SYS_GETTID)
}

#[inline]
pub fn rt_sigprocmask(how: i64, set: *const u64, oldset: *mut u64, sigsetsize: usize) -> i64 {
    raw_syscall7(how, addr(set), addr(oldset), sigsetsize as i64, 0, 0, SYS_RT_SIGPROCMASK)
}

#[inline]
pub fn openat(dirfd: i32, path: *const u8, flags: i64, mode: i64) -> i64 {
    raw_syscall7(dirfd as i64, addr(path), flags, mode, 0, 0, SYS_OPENAT)
}

#[inline]
pub fn unlink(path: *const u8) -> i64 {
    raw_syscall7(addr(path), 0, 0, 0, 0, 0, SYS_UNLINK)
}

#[inline]
pub fn futex(uaddr: *const u32, op: i64, val: i64, timeout: *const c_void) -> i64 {
    raw_syscall7(addr(uaddr), op, val, addr(timeout), 0, 0, SYS_FUTEX)
}

#[inline]
pub fn tkill(tid: i64, sig: i64) -> i64 {
    raw_syscall7(tid, sig, 0, 0, 0, 0, SYS_TKILL)
}

/// `exit_group(status)` — terminates the whole thread group and never returns.
#[inline]
pub fn exit_group(status: i32) -> ! {
    loop {
        raw_syscall7(status as i64, 0, 0, 0, 0, 0, SYS_EXIT_GROUP);
    }
}

// ---- ABI structs (abi-layouts.generated.md) --------------------------------

/// `struct iovec` — sizeof 16, align 8.
#[repr(C)]
pub struct Iovec {
    pub iov_base: *mut c_void,
    pub iov_len: usize,
}

/// `struct msghdr` — sizeof 56, align 8 (padding after `msg_namelen` and a tail
/// pad after `msg_flags` are inserted by the C layout rules).
#[repr(C)]
pub struct Msghdr {
    pub msg_name: *mut c_void,
    pub msg_namelen: u32,
    pub msg_iov: *mut Iovec,
    pub msg_iovlen: usize,
    pub msg_control: *mut c_void,
    pub msg_controllen: usize,
    pub msg_flags: i32,
}

/// `struct cmsghdr` mirror — sizeof 16, align 8 (abi-layouts.generated.md notes
/// the generator uses this x86-64 glibc layout; the payload fds follow it with no
/// `CMSG_ALIGN` padding, bootstrap-handshakes.md §0).
#[repr(C)]
pub struct Cmsghdr {
    pub cmsg_len: usize,
    pub cmsg_level: i32,
    pub cmsg_type: i32,
}

/// `struct sockaddr_un` (x86-64 platform layout; not in the cdef). `sun_path` is
/// 108 bytes, so paths up to 107 bytes plus a NUL fit (bootstrap-handshakes.md §4).
#[repr(C)]
pub struct SockaddrUn {
    pub sun_family: u16,
    pub sun_path: [u8; 108],
}

impl SockaddrUn {
    /// Longest path that fits with its NUL terminator (bootstrap-handshakes.md §4:
    /// "Paths of up to 107 bytes MUST work").
    pub const MAX_PATH: usize = 107;

    /// Build an `AF_UNIX` address for `path`, returning it with the `addrlen` to
    /// pass to `bind`/`connect` (family + path + NUL). `None` if the path is longer
    /// than [`Self::MAX_PATH`].
    pub fn from_path(path: &[u8]) -> Option<(SockaddrUn, usize)> {
        if path.len() > Self::MAX_PATH {
            return None;
        }
        let mut a = SockaddrUn { sun_family: AF_UNIX as u16, sun_path: [0u8; 108] };
        let mut i = 0;
        while i < path.len() {
            a.sun_path[i] = path[i];
            i += 1;
        }
        Some((a, 2 + path.len() + 1))
    }
}

/// `struct robust_list` — sizeof 8, align 8.
#[repr(C)]
pub struct RobustList {
    pub next: *mut RobustList,
}

/// `struct futex_node` — sizeof 16, align 8; `futex` at offset 8 (the `ctid`
/// argument of `clone` is node + 8, native-abi.md §5/§6). A 4-byte tail pad
/// follows `futex`.
#[repr(C)]
pub struct FutexNode {
    pub list: RobustList,
    pub futex: u32,
}
