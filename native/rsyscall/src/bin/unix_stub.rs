//! `rsyscall-unix-stub` — M1 placeholder (bootstrap-handshakes.md §4, §6).
//!
//! The real handshake is M4. For now: print a diagnostic to stderr and exit 1.
#![no_std]
#![no_main]

#[path = "../rt/panic.rs"]
mod panic;

/// Custom entry point (`-Wl,-e,_start`, `-nostartfiles`).
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
    const MSG: &[u8] =
        b"rsyscall-unix-stub: missing environment variable RSYSCALL_UNIX_STUB_SOCK_PATH\n";
    let _ = rsyscall_core::io::write_all(2, MSG);
    rsyscall_core::sys::exit_group(1)
}
