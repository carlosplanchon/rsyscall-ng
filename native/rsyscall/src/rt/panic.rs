//! `#[panic_handler]` for the freestanding artefacts (native-abi.md §9).
//!
//! No unwinding (`panic = "abort"`), no `core::fmt`: a panic in freestanding code
//! is a bug, so terminate the process with a distinctive status. Shared by the
//! cdylib and, via `#[path]`, by each helper executable (each final artefact needs
//! exactly one panic handler).

#[panic_handler]
fn panic(_info: &core::panic::PanicInfo) -> ! {
    rsyscall_core::sys::exit_group(127)
}
