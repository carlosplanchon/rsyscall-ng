//! `librsyscall.so`: the five C-ABI symbols the client loads through the cffi
//! module `rsyscall._raw` (native-abi.md §2, §3).
//!
//! This is a final artefact, so it carries the things `rsyscall-core` deliberately
//! omits: the `#[panic_handler]` and the freestanding `mem*` symbols
//! (native-abi.md §9). The five exports live in `rt/exports.rs`, which the three
//! helper executables include as well. Symbols defined only in `global_asm!` (the
//! `mem*`) stay local and are not part of the cdylib's dynamic exports, which is
//! why the `mem*` go there and the exports are `#[no_mangle]` functions.
#![no_std]

#[path = "rt/mem.rs"]
mod mem;
#[path = "rt/panic.rs"]
mod panic;
#[path = "rt/exports.rs"]
mod exports;
