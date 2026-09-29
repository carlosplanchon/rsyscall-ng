//! Drive `rsyscall_server` over a real `socketpair` with raw bytes and check every
//! server obligation of wire-protocol.md §3-§10. Uses only libc-free std APIs
//! (`std::os::unix::net::UnixStream`) plus raw syscalls through rsyscall-core.
//!
//! All scenarios run in one test, sequentially, because the SIGPIPE scenario
//! changes a process-wide signal disposition.

use rsyscall_core::arch::x86_64::raw_syscall7;
use rsyscall_core::server::serve;
use std::io::{Read, Write};
use std::os::fd::AsRawFd;
use std::os::unix::net::UnixStream;
use std::thread::JoinHandle;

/// x86-64 syscall numbers used by this test harness (public kernel ABI).
const SYS_RT_SIGACTION: i64 = 13;
const SIGPIPE: i64 = 13;

fn req(sys: i64, args: [i64; 6]) -> [u8; 56] {
    let mut b = [0u8; 56];
    b[0..8].copy_from_slice(&sys.to_le_bytes());
    for i in 0..6 {
        b[8 + i * 8..16 + i * 8].copy_from_slice(&args[i].to_le_bytes());
    }
    b
}

/// Spawn a server thread on a fresh socketpair; return the client end, the server
/// fd number (as the client must name it in memory-transfer requests) and the join
/// handle carrying the server's return code.
fn spawn() -> (UnixStream, i32, JoinHandle<i32>) {
    let (client, server) = UnixStream::pair().unwrap();
    let sfd = server.as_raw_fd();
    let h = std::thread::spawn(move || {
        let _keep = server; // keep the fd open for the server's lifetime
        serve(sfd, sfd)
    });
    (client, sfd, h)
}

fn read_i64(s: &mut UnixStream) -> i64 {
    let mut b = [0u8; 8];
    s.read_exact(&mut b).unwrap();
    i64::from_le_bytes(b)
}

fn reset_sigpipe_default() {
    // struct kernel_sigaction { handler; flags; restorer; mask } on x86-64.
    #[repr(C)]
    struct KSigaction {
        handler: usize,
        flags: u64,
        restorer: usize,
        mask: u64,
    }
    let act = KSigaction { handler: 0 /* SIG_DFL */, flags: 0, restorer: 0, mask: 0 };
    let r = raw_syscall7(
        SIGPIPE,
        (&act as *const KSigaction) as usize as i64,
        0,               // oldact
        8,               // sigsetsize
        0,
        0,
        SYS_RT_SIGACTION,
    );
    assert_eq!(r, 0, "rt_sigaction(SIGPIPE, SIG_DFL) failed: {r}");
}

#[test]
fn server_wire_protocol() {
    let my_pid = std::process::id() as i64;

    // -- exact 56-byte read, single request delivered whole (getpid) -----------
    {
        let (mut c, _sfd, h) = spawn();
        c.write_all(&req(39, [0; 6])).unwrap();
        assert_eq!(read_i64(&mut c), my_pid);
        drop(c);
        assert_eq!(h.join().unwrap(), 0);
    }

    // -- request delivered in 10 / 30 / 16-byte pieces -------------------------
    {
        let (mut c, _sfd, h) = spawn();
        let r = req(39, [0; 6]);
        c.write_all(&r[0..10]).unwrap();
        c.flush().unwrap();
        c.write_all(&r[10..40]).unwrap();
        c.flush().unwrap();
        c.write_all(&r[40..56]).unwrap();
        c.flush().unwrap();
        assert_eq!(read_i64(&mut c), my_pid);
        drop(c);
        assert_eq!(h.join().unwrap(), 0);
    }

    // -- two pipelined requests in one send ------------------------------------
    {
        let (mut c, _sfd, h) = spawn();
        let mut two = Vec::new();
        two.extend_from_slice(&req(39, [0; 6]));
        two.extend_from_slice(&req(39, [0; 6]));
        c.write_all(&two).unwrap();
        assert_eq!(read_i64(&mut c), my_pid);
        assert_eq!(read_i64(&mut c), my_pid);
        drop(c);
        assert_eq!(h.join().unwrap(), 0);
    }

    // -- memory write: recvfrom(server_fd, dest, len, MSG_WAITALL) + inline data
    {
        let (mut c, sfd, h) = spawn();
        let mut dest = [0u8; 44];
        let payload: Vec<u8> = (0..44u8).collect();
        let dest_addr = dest.as_mut_ptr() as usize as i64;
        c.write_all(&req(45, [sfd as i64, dest_addr, 44, 0x100 /* MSG_WAITALL */, 0, 0]))
            .unwrap();
        c.write_all(&payload).unwrap(); // the raw bytes follow the request
        assert_eq!(read_i64(&mut c), 44, "recvfrom must return len");
        assert_eq!(&dest[..], &payload[..], "server stored the bytes at dest");
        drop(c);
        assert_eq!(h.join().unwrap(), 0);
    }

    // -- memory read: sendto(server_fd, src, len) then the 8-byte response ------
    {
        let (mut c, sfd, h) = spawn();
        let src: Vec<u8> = (100..144u8).collect();
        let src_addr = src.as_ptr() as usize as i64;
        c.write_all(&req(44, [sfd as i64, src_addr, 44, 0, 0, 0])).unwrap();
        let mut data = [0u8; 44];
        c.read_exact(&mut data).unwrap(); // data precedes the response
        assert_eq!(&data[..], &src[..], "server sent the bytes at src");
        assert_eq!(read_i64(&mut c), 44, "sendto must return len");
        drop(c);
        assert_eq!(h.join().unwrap(), 0);
    }

    // -- raw -errno passthrough: close(-1) -> -EBADF (-9) ----------------------
    {
        let (mut c, _sfd, h) = spawn();
        c.write_all(&req(3, [-1i64, 0, 0, 0, 0, 0])).unwrap();
        assert_eq!(read_i64(&mut c), -9, "close(-1) must return -EBADF unchanged");
        drop(c);
        assert_eq!(h.join().unwrap(), 0);
    }

    // -- EOF at the start of a request: serve returns 0 ------------------------
    {
        let (c, _sfd, h) = spawn();
        drop(c);
        assert_eq!(h.join().unwrap(), 0);
    }

    // -- SIGPIPE safety: a response to a vanished peer must not kill us ---------
    // Reset SIGPIPE to SIG_DFL so a broken-pipe write would terminate the process
    // unless the server suppresses the signal with MSG_NOSIGNAL. Run last.
    {
        reset_sigpipe_default();
        let (mut c, _sfd, h) = spawn();
        c.write_all(&req(39, [0; 6])).unwrap(); // one request, then vanish
        drop(c); // close the reader before the server writes its response
        // If MSG_NOSIGNAL is honoured, the write fails with -EPIPE and serve
        // returns 2 (write error); the process is still alive to assert it.
        let rc = h.join().unwrap();
        assert!(rc == 2 || rc == 0, "serve returned {rc} (expected 2 write-error, or 0 if it saw EOF first)");
    }
}
