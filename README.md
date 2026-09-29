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
The small native part (a syscall server, a `clone` trampoline and a futex
helper, currently C + x86_64 assembly upstream) will be rewritten in Rust; until
then the unmodified upstream C is built locally as a *differential test
oracle*.

## Status: phase 0

- [x] upstream `python/` imported with history (commit `2a36209`, 2022-07-25)
- [x] compatibility patches for Python 3.12+ / current trio and outcome
- [x] test harness migrated off `trio.MultiError`
- [x] baseline of the upstream test-suite recorded against the original C
      backend (`tests/baseline-c.txt`)
- [ ] protocol specification, Rust native crate, wheels, CI (later phases)

## Layout

| Path                       | What                                                        |
|----------------------------|-------------------------------------------------------------|
| `python/`                  | upstream Python package tree (`rsyscall`, `dneio`, `arepl`, `wish`, `rsysapps`) |
| `scripts/`                 | oracle build, venv setup, baseline runner, smoke test        |
| `tests/baseline-c.txt`     | per-test status of the suite against the C backend          |
| `reference/` (gitignored)  | pinned upstream clone and the locally built C oracle        |
| `.venv/` (gitignored)      | development virtualenv created by `make venv`               |

## Quick start

Requirements: Linux x86_64, git, [uv](https://docs.astral.sh/uv/), a C
toolchain with autotools, libtool and pkg-config, and the Linux kernel headers.

```sh
make oracle     # clone upstream at the pinned commit and build c/ into reference/prefix
make venv       # .venv with an editable install of python/ built against the oracle
make hello      # clone a child process, write to its stdout, exec `echo`
make baseline   # run the suite and (re)generate tests/baseline-c.txt
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
description of reality, not a promise that everything passes.

## Licensing

New code is MIT, Copyright (c) 2026 Carlos Andrés Planchón Prestes (see
`LICENSE`). `python/` is MIT per upstream package metadata, Copyright
2018-2022 Spencer Baugh and contributors. Upstream `c/` is intentionally not
part of this repository. See `NOTICE` for details.
