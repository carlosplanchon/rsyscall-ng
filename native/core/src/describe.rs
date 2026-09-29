//! Describe structs and their serialisation (bootstrap-handshakes.md §0, §2-§4;
//! native-abi.md §8; layouts from abi-layouts.generated.md).
//!
//! A helper executable writes the exact in-memory image of one of these structs on
//! the data socket, then the length-prefixed strings whose counts the struct
//! carries. The layouts below carry explicit `_pad` fields wherever the C layout
//! has padding, so every byte of the image is initialised (and zero, as §0
//! recommends) and `as_bytes` is sound.

use crate::cstr;
use crate::io::write_all;

/// `struct rsyscall_symbol_table` (native-abi.md §8): the absolute run-time
/// addresses, in the describing process, of the four entry points, in this order.
/// sizeof = 32.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct SymbolTable {
    pub rsyscall_server: u64,
    pub rsyscall_persistent_server: u64,
    pub rsyscall_futex_helper: u64,
    pub rsyscall_trampoline: u64,
}

/// `struct rsyscall_bootstrap` (§2). sizeof = 56, no padding.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Bootstrap {
    pub symbols: SymbolTable,
    pub pid: i32,
    pub listening_sock: i32,
    pub syscall_sock: i32,
    pub data_sock: i32,
    pub envp_count: u64,
}

/// `struct rsyscall_stdin_bootstrap` (§3). sizeof = 64; `_pad` is the 4-byte
/// padding at offset 52.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct StdinBootstrap {
    pub symbols: SymbolTable,
    pub pid: i32,
    pub syscall_fd: i32,
    pub data_fd: i32,
    pub futex_memfd: i32,
    pub connecting_fd: i32,
    pub _pad: u32,
    pub envp_count: u64,
}

/// `struct rsyscall_unix_stub` (§4). sizeof = 80; `_pad` is the 4-byte padding at
/// offset 52. `sigmask`: bit `n-1` set means signal `n` is blocked.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct UnixStub {
    pub symbols: SymbolTable,
    pub pid: i32,
    pub syscall_fd: i32,
    pub data_fd: i32,
    pub futex_memfd: i32,
    pub connecting_fd: i32,
    pub _pad: u32,
    pub argc: u64,
    pub envp_count: u64,
    pub sigmask: u64,
}

/// Marker for `#[repr(C)]` structs made only of plain integers with no implicit
/// padding, so their whole in-memory image is initialised bytes.
///
/// # Safety
/// Implementors must have no padding bytes and no fields with invalid bit patterns.
pub unsafe trait Plain: Sized {
    /// The exact wire image (bootstrap-handshakes.md §0 "Fixed-layout struct").
    fn as_bytes(&self) -> &[u8] {
        // SAFETY: `Plain` guarantees every byte is initialised; the slice covers
        // exactly one value.
        unsafe { core::slice::from_raw_parts(self as *const Self as *const u8, core::mem::size_of::<Self>()) }
    }
}

// SAFETY: integers only, explicit padding fields, verified against the vectors.
unsafe impl Plain for SymbolTable {}
unsafe impl Plain for Bootstrap {}
unsafe impl Plain for StdinBootstrap {}
unsafe impl Plain for UnixStub {}

/// The 8-byte little-endian length prefix of a string (§0, vector `lp_string`).
#[inline]
pub fn lp_len_bytes(n: usize) -> [u8; 8] {
    (n as u64).to_le_bytes()
}

/// Write one length-prefixed string: `u64` LE byte count, then the bytes, no NUL
/// (bootstrap-handshakes.md §0).
pub fn write_lp_string(fd: i32, s: &[u8]) -> Result<(), ()> {
    write_all(fd, &lp_len_bytes(s.len()))?;
    write_all(fd, s)
}

/// Write the process's environment entries verbatim, one length-prefixed string
/// each, skipping entries without `=` exactly as [`cstr::count_env`] skips them.
///
/// # Safety
/// As for [`cstr::CStrArray::new`].
pub unsafe fn write_env(fd: i32, envp: *const *const u8) -> Result<(), ()> {
    // SAFETY: forwarded contract.
    for e in unsafe { cstr::env_entries(envp) } {
        write_lp_string(fd, e)?;
    }
    Ok(())
}
