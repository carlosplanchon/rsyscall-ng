//! Drive `serve_persistent` end to end (bootstrap-handshakes.md §5;
//! wire-protocol.md §10): serve, client SHUT_WR, server shuts its fds and accepts
//! again, reconnection handshakes with count 2 (success), 1 and 3 (failures),
//! and the socket path is never unlinked. Python-free: std Unix sockets plus raw
//! `sendmsg` built from rsyscall-core's own `Msghdr`/`Iovec`/`ControlBuf`.
//!
//! The server runs in a detached thread of this process, so received fd numbers
//! can be inspected through /proc/self/fd.

use core::ffi::c_void;
use rsyscall_core::cmsg::{cmsg_len, ControlBuf};
use rsyscall_core::persistent::serve_persistent;
use rsyscall_core::sys::{self, Iovec, Msghdr};
use std::io::{ErrorKind, Read, Write};
use std::net::Shutdown;
use std::os::fd::AsRawFd;
use std::os::unix::net::{UnixListener, UnixStream};
use std::time::Duration;

const T: Duration = Duration::from_secs(5);

fn req_getpid() -> [u8; 56] {
    let mut b = [0u8; 56];
    b[0..8].copy_from_slice(&39i64.to_le_bytes());
    b
}

fn getpid_over(s: &mut UnixStream, what: &str) {
    s.set_read_timeout(Some(T)).unwrap();
    s.write_all(&req_getpid()).unwrap();
    let mut r = [0u8; 8];
    s.read_exact(&mut r).unwrap_or_else(|e| panic!("{what}: no response: {e}"));
    assert_eq!(i64::from_le_bytes(r), std::process::id() as i64, "{what}: getpid response");
}

fn expect_eof(s: &mut UnixStream, what: &str) {
    s.set_read_timeout(Some(T)).unwrap();
    let mut b = [0u8; 16];
    match s.read(&mut b) {
        Ok(0) => {}
        Ok(n) => panic!("{what}: expected EOF, got {n} bytes"),
        Err(e) => panic!("{what}: expected EOF, got {e}"),
    }
}

fn expect_no_eof_yet(s: &mut UnixStream, what: &str) {
    s.set_read_timeout(Some(Duration::from_millis(300))).unwrap();
    let mut b = [0u8; 16];
    match s.read(&mut b) {
        Ok(0) => panic!("{what}: unexpected EOF (the server closed that fd)"),
        Ok(n) => panic!("{what}: unexpected {n} bytes"),
        Err(e) if e.kind() == ErrorKind::WouldBlock || e.kind() == ErrorKind::TimedOut => {}
        Err(e) => panic!("{what}: unexpected error {e}"),
    }
}

fn fd_is_open(fd: i32) -> bool {
    std::fs::read_link(format!("/proc/self/fd/{fd}")).is_ok()
}

/// The client side of the handshake: the 4-byte count, then one `sendmsg` with a
/// 1-byte iovec and the unpadded cmsg image of vectors `scm_rights_*`
/// (`msg_controllen == cmsg_len == 16 + 4n`).
fn send_handshake(conn: &mut UnixStream, count: i32, fds: &[i32]) {
    conn.write_all(&count.to_le_bytes()).unwrap();
    let mut byte = [0u8; 1];
    let mut iov = Iovec { iov_base: byte.as_mut_ptr() as *mut c_void, iov_len: 1 };
    let mut ctrl = ControlBuf::new();
    let clen = cmsg_len(fds.len());
    ctrl.0[0..8].copy_from_slice(&(clen as u64).to_le_bytes());
    ctrl.0[8..12].copy_from_slice(&1i32.to_le_bytes()); // SOL_SOCKET
    ctrl.0[12..16].copy_from_slice(&1i32.to_le_bytes()); // SCM_RIGHTS
    for (i, fd) in fds.iter().enumerate() {
        ctrl.0[16 + 4 * i..20 + 4 * i].copy_from_slice(&fd.to_le_bytes());
    }
    let msg = Msghdr {
        msg_name: core::ptr::null_mut(),
        msg_namelen: 0,
        msg_iov: &mut iov as *mut Iovec,
        msg_iovlen: 1,
        msg_control: ctrl.0.as_mut_ptr() as *mut c_void,
        msg_controllen: clen,
        msg_flags: 0,
    };
    let r = sys::sendmsg(conn.as_raw_fd(), &msg as *const Msghdr, 0);
    assert_eq!(r, 1, "sendmsg with {} fds", fds.len());
}

fn read_reply(conn: &mut UnixStream, count: usize) -> Vec<i32> {
    conn.set_read_timeout(Some(T)).unwrap();
    let mut b = vec![0u8; 4 * count];
    conn.read_exact(&mut b).unwrap_or_else(|e| panic!("handshake reply: {e}"));
    b.chunks(4).map(|c| i32::from_le_bytes(c.try_into().unwrap())).collect()
}

#[test]
fn persistent_server_reconnects() {
    let dir = std::env::temp_dir().join(format!("rsyscall-ng-persistent-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("sock");

    // The client creates the listening socket (blocking) and hands its fd over;
    // the server must never bind/listen again or change its flags.
    let listener = UnixListener::bind(&path).unwrap();
    let lfd = listener.as_raw_fd();
    let (mut client0, server0) = UnixStream::pair().unwrap();
    let sfd = server0.as_raw_fd();
    std::thread::spawn(move || {
        let _keep = (listener, server0);
        serve_persistent(sfd, sfd, lfd)
    });

    // A: serve on the initial connection.
    getpid_over(&mut client0, "initial connection");

    // B: client SHUT_WR -> the server finishes, shuts its end RDWR (we read EOF),
    //    keeps the fd open for the client's GC, and goes back to accepting.
    client0.shutdown(Shutdown::Write).unwrap();
    expect_eof(&mut client0, "after client SHUT_WR");
    assert!(fd_is_open(sfd), "server must shut down, not close, the old fd");

    // C: reconnect with count=2 and two fds (new syscall socket, new data socket).
    let mut conn1 = UnixStream::connect(&path).unwrap();
    let (mut a1, b1) = UnixStream::pair().unwrap();
    let (mut a2, b2) = UnixStream::pair().unwrap();
    send_handshake(&mut conn1, 2, &[b1.as_raw_fd(), b2.as_raw_fd()]);
    drop(b1);
    drop(b2); // the server's received copies are now the only server-side ends
    let reply = read_reply(&mut conn1, 2);
    assert_eq!(reply.len(), 2);
    assert!(reply[0] >= 0 && reply[1] >= 0 && reply[0] != reply[1], "reply {reply:?}");
    expect_eof(&mut conn1, "server closes the accepted connection right after the reply");
    assert!(fd_is_open(reply[0]) && fd_is_open(reply[1]), "received fds stay open");
    getpid_over(&mut a1, "requests on the new fd[0] get responses");
    expect_no_eof_yet(&mut a2, "fd[1] stays open and untouched");

    // Back to accepting: SHUT_WR on the new connection.
    a1.shutdown(Shutdown::Write).unwrap();
    expect_eof(&mut a1, "after client SHUT_WR on fd[0]");
    assert!(fd_is_open(reply[0]), "fd[0] shut down but not closed");
    assert!(fd_is_open(reply[1]), "fd[1] still untouched");

    // D: count=1 with two fds -> handshake failure (spec §5 default): no reply,
    //    connection closed, received fds closed, still listening.
    let mut conn2 = UnixStream::connect(&path).unwrap();
    let (mut a3, b3) = UnixStream::pair().unwrap();
    let (mut a4, b4) = UnixStream::pair().unwrap();
    send_handshake(&mut conn2, 1, &[b3.as_raw_fd(), b4.as_raw_fd()]);
    drop(b3);
    drop(b4);
    expect_eof(&mut conn2, "count=1 with two fds: connection closed without a reply");
    expect_eof(&mut a3, "count=1: received fd[0] closed by the server");
    expect_eof(&mut a4, "count=1: received fd[1] closed by the server");

    // E: count=3 with two fds -> same.
    let mut conn3 = UnixStream::connect(&path).unwrap();
    let (mut a5, b5) = UnixStream::pair().unwrap();
    let (mut a6, b6) = UnixStream::pair().unwrap();
    send_handshake(&mut conn3, 3, &[b5.as_raw_fd(), b6.as_raw_fd()]);
    drop(b5);
    drop(b6);
    expect_eof(&mut conn3, "count=3 with two fds: connection closed without a reply");
    expect_eof(&mut a5, "count=3: received fd[0] closed by the server");
    expect_eof(&mut a6, "count=3: received fd[1] closed by the server");

    // C': still accepting and serving after the two failures.
    let mut conn4 = UnixStream::connect(&path).unwrap();
    let (mut a7, b7) = UnixStream::pair().unwrap();
    let (_a8, b8) = UnixStream::pair().unwrap();
    send_handshake(&mut conn4, 2, &[b7.as_raw_fd(), b8.as_raw_fd()]);
    drop(b7);
    drop(b8);
    let reply = read_reply(&mut conn4, 2);
    expect_eof(&mut conn4, "connection closed after the reply");
    getpid_over(&mut a7, "fd[0] after two failed handshakes");
    assert!(fd_is_open(reply[1]), "fd[1] open after the third handshake");

    // F: the server never unlinks the socket path.
    assert!(std::fs::metadata(&path).is_ok(), "socket path must still exist");
    let _ = std::fs::remove_file(&path);
    let _ = std::fs::remove_dir(&dir);
}
