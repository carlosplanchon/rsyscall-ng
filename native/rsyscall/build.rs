//! Link flags for the freestanding artefacts (native-abi.md §2, §9).
//!
//! Directive names verified against the Cargo book (build-scripts reference):
//! `cargo::rustc-link-arg-cdylib` and `cargo::rustc-link-arg-bins`. One `println!`
//! per flag, as the plan requires.
//!
//! Fallbacks noted in the plan, if gcc 16 rejects a combination: drop
//! `-nostdlib`/`-nostartfiles` for the cdylib, or build the bins with
//! `-C relocation-model=static`.

fn main() {
    // Shared object `librsyscall.so`: eager binding (BIND_NOW), bind our own
    // globals internally, forbid undefined symbols, no libc / no CRT startup,
    // fixed soname.
    for flag in [
        "-Wl,-z,now",
        "-Wl,-Bsymbolic",
        "-Wl,-z,defs",
        "-nostdlib",
        "-nostartfiles",
        "-Wl,-soname,librsyscall.so",
    ] {
        println!("cargo::rustc-link-arg-cdylib={flag}");
    }

    // Helper executables: static, non-PIE ET_EXEC with our own `_start` entry and
    // dead-code elimination.
    for flag in [
        "-nostdlib",
        "-nostartfiles",
        "-static",
        "-no-pie",
        "-Wl,-e,_start",
        "-Wl,--gc-sections",
    ] {
        println!("cargo::rustc-link-arg-bins={flag}");
    }

    println!("cargo::rerun-if-changed=build.rs");
}
