//! Persistent server (native-abi.md §3.3; wire-protocol.md §10;
//! bootstrap-handshakes.md §5).
//!
//! Serve the current connection; when it ends (the client's `SHUT_WR` seen as
//! EOF, or an error) make the old fds unusable for the peer and go back to
//! accepting on `listensock`; run the reconnection handshake on each accepted
//! connection and, once one succeeds, serve on the first received fd. Never exit
//! on disconnect, never unlink or rebind the socket path, never change the
//! listening socket.

use crate::cmsg::{self, MAX_FDS};
use crate::io;
use crate::server::serve;
use crate::sys::{self, consts::*};
use core::ptr::null_mut;

/// `int rsyscall_persistent_server(int infd, int outfd, int listensock)`
/// (native-abi.md §3.3).
///
/// Returns only when `accept4` on `listensock` fails with something other than
/// `EINTR`/`ECONNABORTED`; the value is non-zero and the exported wrapper turns it
/// into `exit_group` with a non-zero status (§3.3 Recommended default).
pub fn serve_persistent(infd: i32, outfd: i32, listensock: i32) -> i32 {
    let mut infd = infd;
    let mut outfd = outfd;
    loop {
        // wire-protocol.md §10: finish the request in progress, write its response,
        // then treat EOF on infd as the end of the connection. A write error (peer
        // gone) ends the connection the same way; `serve` never raises SIGPIPE.
        let _ = serve(infd, outfd);

        // bootstrap-handshakes.md §5 "Disconnect": make our end unusable for the
        // peer with shutdown(SHUT_RDWR) on infd and on outfd, and leave the fds to
        // the client's garbage collection (Recommended default: do not close).
        let _ = sys::shutdown(infd, SHUT_RDWR);
        let _ = sys::shutdown(outfd, SHUT_RDWR);

        // Accept until a reconnection handshake succeeds.
        let newfd = loop {
            let conn = loop {
                let r = sys::accept4(listensock, null_mut(), null_mut(), SOCK_CLOEXEC);
                if r >= 0 {
                    break r as i32;
                }
                if r == -EINTR || r == -ECONNABORTED {
                    continue;
                }
                // native-abi.md §3.3: accept failure is Unspecified in v0;
                // Recommended default: terminate the process with a non-zero status.
                return 1;
            };
            match handshake(conn) {
                Ok(fd0) => {
                    // §5: after the reply, close the accepted connection fd and serve
                    // on fd[0]; fd[1..] stay open and untouched.
                    let _ = sys::close(conn);
                    break fd0;
                }
                // The handshake closed whatever it received and the connection;
                // keep listening (§5 Unspecified-in-v0 default for a bad count).
                Err(()) => continue,
            }
        };
        infd = newfd;
        outfd = newfd;
    }
}

/// Decode the native `int32` fd count that opens the handshake
/// (vector `persistent_count`).
#[inline]
pub fn decode_count(b: &[u8; 4]) -> i32 {
    i32::from_le_bytes(*b)
}

/// Encode the reply: the received fd numbers as native `int32`, in received order
/// (vector `persistent_reply`). Returns the number of bytes written to `out`.
pub fn encode_reply(fds: &[i32], out: &mut [u8; 4 * MAX_FDS]) -> usize {
    let n = if fds.len() > MAX_FDS { MAX_FDS } else { fds.len() };
    let mut i = 0;
    while i < n {
        let b = fds[i].to_le_bytes();
        out[4 * i] = b[0];
        out[4 * i + 1] = b[1];
        out[4 * i + 2] = b[2];
        out[4 * i + 3] = b[3];
        i += 1;
    }
    4 * n
}

fn close_all(fds: &[i32; MAX_FDS], n: usize) {
    let mut i = 0;
    while i < n {
        let _ = sys::close(fds[i]);
        i += 1;
    }
}

/// The reconnection handshake on an accepted connection (bootstrap-handshakes.md
/// §5): read exactly 4 bytes (`count`), receive exactly one SCM_RIGHTS message,
/// validate `1 <= count <= MAX_FDS` and `nfds == count`, reply with exactly
/// `count` `int32` fd numbers in received order, and return fd[0].
///
/// On any failure every received fd and the connection are closed (nothing
/// leaks) and `Err` tells the caller to keep accepting.
fn handshake(conn: i32) -> Result<i32, ()> {
    // step 1: exactly 4 bytes before recvmsg (no read-ahead into the fd message).
    let mut cb = [0u8; 4];
    if io::read_exact(conn, &mut cb).is_err() {
        let _ = sys::close(conn);
        return Err(());
    }
    let count = decode_count(&cb);

    // step 2: exactly one SCM_RIGHTS message.
    let mut fds = [0i32; MAX_FDS];
    let nfds = match cmsg::recv_fds(conn, &mut fds) {
        Ok(n) => n,
        Err(_) => {
            let _ = sys::close(conn);
            return Err(());
        }
    };

    // A count that does not match the fds actually received is Unspecified in v0;
    // Recommended default: close the received fds and the connection, keep listening.
    if count < 1 || count as usize > MAX_FDS || nfds != count as usize {
        close_all(&fds, nfds);
        let _ = sys::close(conn);
        return Err(());
    }

    // step 3: exactly `count` int32 fd numbers, received order.
    let mut reply = [0u8; 4 * MAX_FDS];
    let len = encode_reply(&fds[..nfds], &mut reply);
    if io::write_all(conn, &reply[..len]).is_err() {
        close_all(&fds, nfds);
        let _ = sys::close(conn);
        return Err(());
    }
    Ok(fds[0])
}
