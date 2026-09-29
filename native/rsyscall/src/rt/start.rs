//! Process entry for the static helper executables (linked `-nostdlib
//! -nostartfiles -static -no-pie -Wl,-e,_start`, see build.rs).
//!
//! `_start` hands the initial stack pointer to `entry`, which decodes
//! argc/argv/envp per the x86-64 process-start layout (argc at `sp`, then the
//! argv pointers, a NULL, the envp pointers, a NULL), calls the binary's
//! `main(argc, argv, envp) -> i32` and terminates the process with its status.
//! The stack is 16-byte aligned before the call into Rust.

core::arch::global_asm!(
    ".text",
    ".globl _start",
    ".type _start, @function",
    "_start:",
    "xor ebp, ebp",   // outermost frame
    "mov rdi, rsp",   // initial stack pointer -> entry(sp)
    "and rsp, -16",   // ABI alignment for the call below
    "call {entry}",
    "ud2",            // entry never returns
    entry = sym entry,
);

extern "C" fn entry(sp: *const usize) -> ! {
    // SAFETY: `sp` is the initial stack pointer the kernel set up: `argc`, then
    // `argc` argv pointers, NULL, the envp pointers, NULL.
    let argc = unsafe { *sp };
    let argv = unsafe { sp.add(1) } as *const *const u8;
    let envp = unsafe { argv.add(argc + 1) };
    let status = crate::main(argc, argv, envp);
    rsyscall_core::sys::exit_group(status)
}
