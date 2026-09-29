//! `rsyscall-bootstrap` (ssh) — M1 placeholder (bootstrap-handshakes.md §2, §6).
//!
//! The real handshake is M4. For now: print a usage line to stderr and exit 1, so
//! the crate builds and installs with the expected binary present.
#![no_std]
#![no_main]

#[path = "../rt/panic.rs"]
mod panic;

/// Custom entry point (`-Wl,-e,_start`, `-nostartfiles`). At process start `rsp`
/// points at `argc`, 16-byte aligned; M1 ignores argv/envp.
#[unsafe(naked)]
#[unsafe(no_mangle)]
pub extern "C" fn _start() -> ! {
    core::arch::naked_asm!(
        "xor ebp, ebp",
        "and rsp, -16",
        "call {entry}",
        "ud2",
        entry = sym entry,
    )
}

extern "C" fn entry() -> ! {
    const MSG: &[u8] = b"rsyscall-bootstrap: usage: <path> <type>\n";
    let _ = rsyscall_core::io::write_all(2, MSG);
    rsyscall_core::sys::exit_group(1)
}
