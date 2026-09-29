//! One-line stderr diagnostics for the helper executables
//! (bootstrap-handshakes.md §6 Recommended default: `<prog>: <msg>[: <errno text>]`
//! on stderr, non-zero exit, never anything on stdout).
//!
//! No `core::fmt`: the line is emitted as a few `write_all` calls, and errno
//! numbers are mapped through a small table with a numeric fallback.

use crate::cstr::fmt_decimal;
use crate::io::write_all;
use crate::sys::consts::*;

/// Text for an errno number, in the wording the oracle's diagnostics were observed
/// with (e.g. `No such file or directory`, `Socket operation on non-socket`,
/// `Connection refused`). Unknown values become `Unknown error <n>` in `buf`.
pub fn errno_text(e: i64, buf: &mut [u8; 40]) -> &[u8] {
    let s: &'static [u8] = match e {
        EPERM => b"Operation not permitted",
        ENOENT => b"No such file or directory",
        EINTR => b"Interrupted system call",
        EBADF => b"Bad file descriptor",
        EAGAIN => b"Resource temporarily unavailable",
        EACCES => b"Permission denied",
        EEXIST => b"File exists",
        ENOTDIR => b"Not a directory",
        EINVAL => b"Invalid argument",
        EMFILE => b"Too many open files",
        EPIPE => b"Broken pipe",
        ENAMETOOLONG => b"File name too long",
        ENOTSOCK => b"Socket operation on non-socket",
        EADDRINUSE => b"Address already in use",
        ECONNABORTED => b"Software caused connection abort",
        ECONNREFUSED => b"Connection refused",
        _ => {
            const PREFIX: &[u8] = b"Unknown error ";
            let mut i = 0;
            while i < PREFIX.len() {
                buf[i] = PREFIX[i];
                i += 1;
            }
            let mut d = [0u8; 20];
            let digits = fmt_decimal(if e < 0 { (-e) as u64 } else { e as u64 }, &mut d);
            let mut j = 0;
            while j < digits.len() {
                buf[i + j] = digits[j];
                j += 1;
            }
            let n = i + digits.len();
            return &buf[..n];
        }
    };
    let n = s.len();
    let mut i = 0;
    while i < n {
        buf[i] = s[i];
        i += 1;
    }
    &buf[..n]
}

/// Write `<prog>: <parts...>[: <errno text>]\n` to `fd`. Errors are ignored:
/// a diagnostic that cannot be written has nowhere else to go.
pub fn diag_to(fd: i32, prog: &[u8], parts: &[&[u8]], errno: Option<i64>) {
    let _ = write_all(fd, prog);
    let _ = write_all(fd, b": ");
    for p in parts {
        let _ = write_all(fd, p);
    }
    if let Some(e) = errno {
        let _ = write_all(fd, b": ");
        let mut buf = [0u8; 40];
        let _ = write_all(fd, errno_text(e, &mut buf));
    }
    let _ = write_all(fd, b"\n");
}

/// `<prog>: <msg>[: <errno text>]` on stderr.
pub fn diag(prog: &[u8], msg: &[u8], errno: Option<i64>) {
    diag_to(2, prog, &[msg], errno);
}

/// `<prog>: <a><b>[: <errno text>]` on stderr (e.g. `unknown type ` + `argv[1]`).
pub fn diag2(prog: &[u8], a: &[u8], b: &[u8], errno: Option<i64>) {
    diag_to(2, prog, &[a, b], errno);
}

/// `<prog>: <a><b><c>[: <errno text>]` on stderr (e.g. `connect(` + path + `)`).
pub fn diag3(prog: &[u8], a: &[u8], b: &[u8], c: &[u8], errno: Option<i64>) {
    diag_to(2, prog, &[a, b, c], errno);
}
