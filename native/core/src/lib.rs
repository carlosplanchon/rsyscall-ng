//! rsyscall-ng native core (clean-room, from docs/spec).
//!
//! Freestanding building blocks shared by the final artefacts (the `rsyscall`
//! cdylib and the helper executables): the x86-64 assembly primitives, the raw
//! syscall wrappers, the wire codec and the syscall server loop.
//!
//! This crate is `#![no_std]` and defines **no** `#[panic_handler]` and **no**
//! `mem*` symbols, so it can be linked into ordinary `std` test binaries
//! (native-abi.md §9; the reviewer's plan). Those symbols live only in the final
//! artefacts.
#![no_std]
#![deny(unsafe_op_in_unsafe_fn)]

pub mod arch;
pub mod cmsg;
pub mod cstr;
pub mod describe;
pub mod diag;
pub mod io;
pub mod persistent;
pub mod server;
pub mod sys;
pub mod wire;
