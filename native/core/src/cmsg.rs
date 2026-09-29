//! SCM_RIGHTS control-message handling (bootstrap-handshakes.md §0, §5).
//!
//! The client sends one `sendmsg` with a single 1-byte iovec and one control
//! message `{ cmsg_len = 16 + 4n, SOL_SOCKET, SCM_RIGHTS }` followed by `n`
//! native `int` fds, with no `CMSG_ALIGN` padding (vectors `scm_rights_*`). The
//! kernel re-encodes the control data for the receiver with `CMSG_ALIGN` padding,
//! so a receiver must size its buffer as `CMSG_SPACE(4n)` and walk the data by
//! `cmsg_len`, never by the sender's byte count (bootstrap-handshakes.md §0
//! Rationale). The receiver MUST consume the single payload byte and ignore its
//! value, and treats `MSG_CTRUNC` as fatal; fds are received with
//! `MSG_CMSG_CLOEXEC` (§0 Recommended default).

use crate::sys::{self, consts::*, Iovec, Msghdr};
use core::ffi::c_void;

/// Upper bound on fds accepted in one message (the client passes at most 4 today).
pub const MAX_FDS: usize = 16;

/// `sizeof(struct cmsghdr)` on x86-64 (abi-layouts.generated.md, cmsg mirror).
pub const CMSG_HDR_LEN: usize = 16;

/// `CMSG_ALIGN(n)`: round up to the 8-byte alignment of `size_t`.
#[inline]
pub const fn cmsg_align(n: usize) -> usize {
    (n + 7) & !7
}

/// `cmsg_len` for `n` fds: `16 + 4n` (abi-layouts.generated.md, derived constants).
#[inline]
pub const fn cmsg_len(n_fds: usize) -> usize {
    CMSG_HDR_LEN + 4 * n_fds
}

/// `CMSG_SPACE(4n)`: header plus the aligned payload.
#[inline]
pub const fn cmsg_space(n_fds: usize) -> usize {
    CMSG_HDR_LEN + cmsg_align(4 * n_fds)
}

/// Size of the receive control buffer: `CMSG_SPACE(4 * MAX_FDS)` = 80.
pub const CONTROL_LEN: usize = cmsg_space(MAX_FDS);

/// An 8-byte-aligned control buffer (the kernel requires `struct cmsghdr`
/// alignment for `msg_control`).
#[repr(C, align(8))]
pub struct ControlBuf(pub [u8; CONTROL_LEN]);

impl ControlBuf {
    pub const fn new() -> ControlBuf {
        ControlBuf([0u8; CONTROL_LEN])
    }
}

impl Default for ControlBuf {
    fn default() -> Self {
        Self::new()
    }
}

/// Result of walking a control buffer.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Parsed {
    /// fds extracted from every `SOL_SOCKET`/`SCM_RIGHTS` message, in order.
    pub nfds: usize,
    /// total number of control messages seen.
    pub ncmsgs: usize,
    /// how many of them were `SCM_RIGHTS`.
    pub nrights: usize,
    /// a header did not fit, a length was inconsistent, or `MAX_FDS` was exceeded.
    pub malformed: bool,
}

#[inline]
fn rd_u64(b: &[u8], o: usize) -> u64 {
    u64::from_le_bytes([b[o], b[o + 1], b[o + 2], b[o + 3], b[o + 4], b[o + 5], b[o + 6], b[o + 7]])
}

#[inline]
fn rd_i32(b: &[u8], o: usize) -> i32 {
    i32::from_le_bytes([b[o], b[o + 1], b[o + 2], b[o + 3]])
}

/// Pure parser: walk `control` (`msg_controllen` bytes as returned by the kernel,
/// or a sender's unpadded image) and copy the fds of every `SCM_RIGHTS` message
/// into `out`. Bounds are checked before every read, so this never panics on
/// hostile input; it stops at the first inconsistency and reports `malformed`.
pub fn parse_control(control: &[u8], out: &mut [i32; MAX_FDS]) -> Parsed {
    let len = control.len();
    let mut p = Parsed { nfds: 0, ncmsgs: 0, nrights: 0, malformed: false };
    let mut off: usize = 0;
    while off + CMSG_HDR_LEN <= len {
        let clen = rd_u64(control, off) as usize;
        let level = rd_i32(control, off + 8) as i64;
        let ty = rd_i32(control, off + 12) as i64;
        if clen < CMSG_HDR_LEN || clen > len - off {
            p.malformed = true;
            break;
        }
        p.ncmsgs += 1;
        if level == SOL_SOCKET && ty == SCM_RIGHTS {
            p.nrights += 1;
            let data = clen - CMSG_HDR_LEN;
            if data % 4 != 0 {
                p.malformed = true;
                break;
            }
            let n = data / 4;
            let mut i = 0;
            while i < n {
                if p.nfds >= MAX_FDS {
                    p.malformed = true;
                    break;
                }
                out[p.nfds] = rd_i32(control, off + CMSG_HDR_LEN + 4 * i);
                p.nfds += 1;
                i += 1;
            }
            if p.malformed {
                break;
            }
        }
        // The next header starts at CMSG_ALIGN(cmsg_len) (kernel encoding); for a
        // sender's unpadded image this simply runs past the end.
        off += cmsg_align(clen);
    }
    p
}

/// Receive exactly one SCM_RIGHTS message on `fd` (bootstrap-handshakes.md §0):
/// a 1-byte iovec (consumed, value ignored) and a `CMSG_SPACE(4 * MAX_FDS)`
/// control buffer, with `MSG_CMSG_CLOEXEC`. Returns the number of fds written to
/// `out` (in the order sent).
///
/// On `Err` nothing leaks: any fds the kernel installed for a message that then
/// failed validation (`MSG_CTRUNC`, not exactly one cmsg, not `SCM_RIGHTS`,
/// malformed) are closed here. A negative `recvmsg` result or EOF installs
/// nothing.
pub fn recv_fds(fd: i32, out: &mut [i32; MAX_FDS]) -> Result<usize, ()> {
    let mut payload = [0u8; 1];
    let mut iov = Iovec { iov_base: payload.as_mut_ptr() as *mut c_void, iov_len: 1 };
    let mut ctrl = ControlBuf::new();
    let mut msg = Msghdr {
        msg_name: core::ptr::null_mut(),
        msg_namelen: 0,
        msg_iov: &mut iov as *mut Iovec,
        msg_iovlen: 1,
        msg_control: ctrl.0.as_mut_ptr() as *mut c_void,
        msg_controllen: CONTROL_LEN,
        msg_flags: 0,
    };

    let r = loop {
        let r = sys::recvmsg(fd, &mut msg as *mut Msghdr, MSG_CMSG_CLOEXEC);
        if r != -EINTR {
            break r;
        }
    };
    if r <= 0 {
        return Err(());
    }

    let ctrunc = (msg.msg_flags as i64) & MSG_CTRUNC != 0;
    let clen = if msg.msg_controllen > CONTROL_LEN { CONTROL_LEN } else { msg.msg_controllen };
    let p = parse_control(&ctrl.0[..clen], out);

    if ctrunc || p.malformed || p.ncmsgs != 1 || p.nrights != 1 {
        let mut i = 0;
        while i < p.nfds {
            let _ = sys::close(out[i]);
            i += 1;
        }
        return Err(());
    }
    Ok(p.nfds)
}
