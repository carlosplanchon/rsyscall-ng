//! Blocking full-read / full-write helpers over the raw syscalls
//! (wire-protocol.md §3, §5, §6, §10).

use crate::sys;
use crate::sys::consts::{EINTR, ENOTSOCK, MSG_NOSIGNAL};

/// Why a full read could not be completed.
pub enum RecvErr {
    /// 0 bytes at the start of a request: the connection ended cleanly (EOF).
    Eof,
    /// A read error, or 0 bytes in the middle of a request (a truncated request).
    Err,
}

/// Read exactly `buf.len()` bytes, accumulating short reads and retrying `EINTR`
/// (wire-protocol.md §3). 0 bytes before any byte of the request is `Eof`; 0 bytes
/// mid-request is a broken connection (`Err`).
pub fn read_exact(fd: i32, buf: &mut [u8]) -> Result<(), RecvErr> {
    let n = buf.len();
    let mut got: usize = 0;
    while got < n {
        // SAFETY: `got < n <= buf.len()`, so `add(got)` stays within the buffer and
        // the kernel writes at most `n - got` bytes there.
        let dst = unsafe { buf.as_mut_ptr().add(got) };
        let r = sys::read(fd, dst, n - got);
        if r < 0 {
            if r == -EINTR {
                continue;
            }
            return Err(RecvErr::Err);
        }
        if r == 0 {
            return Err(if got == 0 { RecvErr::Eof } else { RecvErr::Err });
        }
        got += r as usize;
    }
    Ok(())
}

/// Write all of `buf`, retrying `EINTR` and looping on partial writes
/// (wire-protocol.md §8). Uses `sendto` with `MSG_NOSIGNAL` so a dead peer yields
/// `-EPIPE` instead of `SIGPIPE` (wire-protocol.md §10); falls back to `write` when
/// the fd is not a socket (`-ENOTSOCK`).
pub fn write_all(fd: i32, buf: &[u8]) -> Result<(), ()> {
    let n = buf.len();
    let mut sent: usize = 0;
    while sent < n {
        // SAFETY: `sent < n <= buf.len()`, so `add(sent)` stays within the buffer.
        let src = unsafe { buf.as_ptr().add(sent) };
        let mut r = sys::sendto(fd, src, n - sent, MSG_NOSIGNAL, core::ptr::null(), 0);
        if r == -ENOTSOCK {
            r = sys::write(fd, src, n - sent);
        }
        if r < 0 {
            if r == -EINTR {
                continue;
            }
            return Err(());
        }
        if r == 0 {
            // A blocking stream should not report a 0-byte write for n > 0; treat it
            // as a broken connection rather than spin forever.
            return Err(());
        }
        sent += r as usize;
    }
    Ok(())
}
