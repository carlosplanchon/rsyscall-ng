# rsyscall-ng native side (Rust, clean-room)

A drop-in replacement for the upstream C native side, implemented in Rust from
`docs/spec/**` only. Built and installed by `scripts/native-install.sh`
(`make native`).

- `core/` — `rsyscall-core`: freestanding (`#![no_std]`) building blocks: the
  x86-64 assembly primitives, raw-syscall wrappers, the wire codec and the syscall
  server loop. No panic handler and no `mem*`, so it links into `std` test binaries.
- `rsyscall/` — `rsyscall-native`: the `librsyscall.so` cdylib exporting the five
  C-ABI symbols, plus the three helper executables and the C header / pkg-config
  template.

Status: M1 (server loop, the three assembly exports, header, minimal binaries and
tests), M2 (parity with the C baseline) and M3 (persistent server: disconnect,
accept, SCM_RIGHTS reconnection handshake) done. M4 (the three helper
executables) and M5 (docs) follow.
