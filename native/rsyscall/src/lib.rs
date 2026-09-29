//! `librsyscall.so`: the five C-ABI symbols the client loads through the cffi
//! module `rsyscall._raw` (native-abi.md §2, §3).
//!
//! This is a final artefact, so it carries the things `rsyscall-core` deliberately
//! omits: the `#[panic_handler]` and the freestanding `mem*` symbols
//! (native-abi.md §9). The three assembly exports are instantiated here from the
//! core macros so they get the exported C names; symbols defined only in
//! `global_asm!` (the `mem*`) stay local and are not part of the cdylib's dynamic
//! exports, which is exactly why the `mem*` go there and the exports are naked
//! `#[no_mangle]` functions.
#![no_std]

#[path = "rt/mem.rs"]
mod mem;
#[path = "rt/panic.rs"]
mod panic;

// The three assembly exports (native-abi.md §3.1, §3.5, §3.4).
rsyscall_core::define_raw_syscall!(#[unsafe(no_mangle)] pub rsyscall_raw_syscall);
rsyscall_core::define_trampoline!(#[unsafe(no_mangle)] pub rsyscall_trampoline);
rsyscall_core::define_futex_helper!(#[unsafe(no_mangle)] pub rsyscall_futex_helper);

/// `int rsyscall_server(int infd, int outfd)` (native-abi.md §3.2; wire-protocol.md §3).
#[unsafe(no_mangle)]
pub extern "C" fn rsyscall_server(infd: i32, outfd: i32) -> i32 {
    rsyscall_core::server::serve(infd, outfd)
}

/// `int rsyscall_persistent_server(int infd, int outfd, int listensock)`
/// (native-abi.md §3.3; bootstrap-handshakes.md §5). Serves, reconnects and serves
/// again forever; `serve_persistent` only returns when `accept` on `listensock`
/// fails, which is Unspecified in v0 (Recommended default: terminate with a
/// non-zero status). It never returns to the trampoline with a success status.
#[unsafe(no_mangle)]
pub extern "C" fn rsyscall_persistent_server(infd: i32, outfd: i32, listensock: i32) -> i32 {
    let _ = rsyscall_core::persistent::serve_persistent(infd, outfd, listensock);
    rsyscall_core::sys::exit_group(1)
}
