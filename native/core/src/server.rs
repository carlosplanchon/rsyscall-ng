//! The syscall server loop (wire-protocol.md §3; native-abi.md §3.2).
//!
//! read one 56-byte request, execute it verbatim as a raw syscall, write the
//! 8-byte response, repeat. No inspection, no filtering, no read-ahead, no
//! buffering across requests, no allocation, no `core::fmt` (native-abi.md §9).

use crate::arch::x86_64::raw_syscall7;
use crate::io::{self, RecvErr};
use crate::wire::{encode_response, Request, REQUEST_LEN};

/// `int rsyscall_server(int infd, int outfd)` (native-abi.md §3.2).
///
/// Returns 0 on EOF, 1 on a read error, 2 on a write error (return value
/// Unspecified in v0; these are the Recommended defaults).
pub fn serve(infd: i32, outfd: i32) -> i32 {
    let mut buf = [0u8; REQUEST_LEN];
    loop {
        match io::read_exact(infd, &mut buf) {
            Ok(()) => {}
            Err(RecvErr::Eof) => return 0,
            Err(RecvErr::Err) => return 1,
        }

        let req = Request::from_bytes(&buf);

        // Execute the raw syscall with all six arguments verbatim (wire-protocol.md
        // §2/§3). exit/exec are executed literally; a clone request's child never
        // returns here (it resumes in the trampoline). -EINTR is passed through.
        let ret = raw_syscall7(
            req.args[0], req.args[1], req.args[2], req.args[3], req.args[4], req.args[5], req.sys,
        );

        // Write the response before reading the next request (wire-protocol.md §3).
        let resp = encode_response(ret);
        if io::write_all(outfd, &resp).is_err() {
            return 2;
        }
    }
}
