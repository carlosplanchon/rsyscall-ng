//! The five exported C-ABI symbols (native-abi.md §3), shared by the cdylib and,
//! through `#[path]`, by each helper executable, so that every artefact carries
//! real `extern "C"` entry points under these names.
//!
//! A helper executable's describe struct reports the absolute run-time addresses
//! of exactly these four wrappers (native-abi.md §8): the client later enters them
//! through the trampoline with the C calling convention, so they must be the
//! `extern "C"` functions, never the Rust-ABI core functions behind them.

use core::ffi::c_void;
use rsyscall_core::describe::SymbolTable;

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

/// `struct rsyscall_symbol_table` for this process (native-abi.md §8): the
/// addresses of the four `extern "C"` entry points above. Unused by the cdylib.
#[allow(dead_code)]
pub fn symbol_table() -> SymbolTable {
    SymbolTable {
        rsyscall_server: rsyscall_server as extern "C" fn(i32, i32) -> i32 as usize as u64,
        rsyscall_persistent_server: rsyscall_persistent_server as extern "C" fn(i32, i32, i32) -> i32
            as usize as u64,
        rsyscall_futex_helper: rsyscall_futex_helper as extern "C" fn(*mut c_void) as usize as u64,
        rsyscall_trampoline: rsyscall_trampoline as extern "C" fn() as usize as u64,
    }
}
