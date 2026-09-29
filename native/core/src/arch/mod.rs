//! Architecture-specific assembly primitives.
//!
//! v0 targets x86-64 LP64 little-endian only (native-abi.md §1).

#[cfg(target_arch = "x86_64")]
pub mod x86_64;
