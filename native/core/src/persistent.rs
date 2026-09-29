//! Persistent server (native-abi.md §3.3; bootstrap-handshakes.md §5).
//!
//! M1 stub: the real reconnection loop (accept on `listensock`, run the handshake,
//! serve again, never exit on disconnect) is M3. For now this serves the current
//! connection once and returns; the cdylib export then terminates the process.

/// M1 stub for `rsyscall_persistent_server`: serve the current connection with the
/// plain loop, then return 1 (the caller in the cdylib turns this into
/// `exit_group(1)`).
pub fn serve_persistent(infd: i32, outfd: i32, _listensock: i32) -> i32 {
    let _ = crate::server::serve(infd, outfd);
    1
}
