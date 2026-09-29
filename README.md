# rsyscall-ng

A modernization of [rsyscall](https://github.com/catern/rsyscall), the
process-independent, type-safe, low-level interface to Linux system calls for
Python. In rsyscall every syscall is a method on a *process object*, which may
be the local interpreter, a child created with `clone`, or a process on a
remote host; new processes start out sharing everything with their parent and
are then shaped with ordinary syscalls (`unshare`, `execve`, ...) instead of
`fork`/`posix_spawn`.

Upstream has been dormant since 2022-07-25 and its PyPI package no longer
installs. rsyscall-ng keeps the upstream Python API (imported with its full git
history under `python/`) and brings it to current Python (>= 3.12) and trio.
The small native part (a syscall server, a `clone` trampoline, a futex helper
and three bootstrap helpers, C + x86_64 assembly upstream) has been
reimplemented in Rust under `native/`, clean-room from the specification in
`docs/spec/`. The unmodified upstream C is still built locally, only as a
*differential test oracle* (`BACKEND=c`).

## Status

- [x] upstream `python/` imported with history (commit `2a36209`, 2022-07-25)
- [x] compatibility patches for Python 3.12+ / current trio and outcome
- [x] test harness migrated off `trio.MultiError`
- [x] baseline of the upstream test-suite recorded against the original C
      backend (`tests/baseline-c.txt`)
- [x] clean-room v0 specification of the native side (`docs/spec/`)
- [x] Rust native side (`native/`): `librsyscall.so` and the three helper
      executables, byte-compatible with the C oracle (`make baseline-diff` is
      empty; `make probe-diff` differs only where the specification leaves
      behaviour unspecified)
- [ ] PyO3/maturin packaging, wheels, CI (later phases)

## Layout

| Path                       | What                                                        |
|----------------------------|-------------------------------------------------------------|
| `python/`                  | upstream Python package tree (`rsyscall`, `dneio`, `arepl`, `wish`, `rsysapps`) |
| `scripts/`                 | oracle build, venv setup, baseline runner, smoke test        |
| `tests/baseline-c.txt`     | per-test status of the suite against the C backend          |
| `docs/spec/`               | clean-room v0 specification of the native side (wire protocol, native ABI, bootstrap handshakes, generated layouts and vectors) |
| `native/`                  | clean-room Rust reimplementation of the native side (`core/` logic and tests, `rsyscall/` cdylib and helper executables); see `native/README.md` |
| `native/prefix/` (gitignored) | the Rust native side installed by `make native` with the oracle's layout |
| `tests/baseline-rust.txt`  | the same suite recorded against the Rust backend; identical to the C one |
| `reference/` (gitignored)  | pinned upstream clone and the locally built C oracle        |
| `.venv/`, `.venv-rust/` (gitignored) | the virtualenv of each backend, created by `make venv` |

## Quick start

Requirements: Linux x86_64, git, [uv](https://docs.astral.sh/uv/), a C
toolchain with autotools, libtool and pkg-config, and the Linux kernel headers.

```sh
make oracle     # clone upstream at the pinned commit and build c/ into reference/prefix
make venv       # .venv with an editable install of python/ built against the oracle
make hello      # clone a child process, write to its stdout, exec `echo`
make baseline   # run the suite and (re)generate tests/baseline-c.txt
```

The Rust native side is selected with `BACKEND=rust`, which switches the prefix
(`native/prefix`), the virtualenv (`.venv-rust`) and the recorded baseline:

```sh
make native                                       # cargo build, install into native/prefix, ELF checks
make venv BACKEND=rust && make hello BACKEND=rust
make baseline BACKEND=rust && make baseline-diff  # tests/baseline-rust.txt vs tests/baseline-c.txt
make probe-diff                                   # black-box probes of the helper executables, both backends
make native-test                                  # the crate's own tests (cargo test -p rsyscall-core)
python3 scripts/header-check.py                   # rsyscall.h against the spec's layout tables
```

The cffi extension `rsyscall._raw` is linked against `reference/prefix/lib`
with an rpath baked in by `make venv`, so `import rsyscall` works from the
`.venv` without further setup. The scripts also export `LD_LIBRARY_PATH` as a
belt-and-braces measure.

## Running tests

```sh
make test PYTEST_ARGS='-k clone'          # any pytest arguments
RSYSCALL_TEST_OPTIONAL=1 make test        # also collect the Nix/ssh/device-dependent modules
```

Modules that need a Nix store, `sshd`, `/dev/fuse`, `/dev/net/tun` or the
upstream `nixdeps` build hook are skipped unless `RSYSCALL_TEST_OPTIONAL=1` is
set. The baseline records the status of every collected test; it is a
description of reality, not a promise that everything passes. `make baseline`
runs every test in its own interpreter: the tests share the module-level
`rsyscall.local_process`, whose state does not survive a test being killed by
the timeout, so in a single process one hanging test would poison the rest.

## Licensing

New code, including all of `native/`, is MIT, Copyright (c) 2026 Carlos Andrés
Planchón Prestes (see `LICENSE`). `python/` is MIT per upstream package
metadata, Copyright 2018-2022 Spencer Baugh and contributors. Upstream `c/` is
intentionally not part of this repository; `native/` was written from
`docs/spec/` alone, without access to it. See `NOTICE` for details.
