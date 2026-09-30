# rsyscall-ng

![rsyscall-ng: process-independent Linux syscalls for Python](https://raw.githubusercontent.com/carlosplanchon/rsyscall-ng/main/assets/banner.jpg)

A modernization of [rsyscall](https://github.com/catern/rsyscall), the
process-independent, type-safe, low-level interface to Linux system calls for
Python. In rsyscall every syscall is a method on a *process object*, which may
be the local interpreter, a child created with `clone`, or a process on a
remote host; new processes start out sharing everything with their parent and
are then shaped with ordinary syscalls (`unshare`, `execve`, ...) instead of
`fork`/`posix_spawn`.

[![CI](https://github.com/carlosplanchon/rsyscall-ng/actions/workflows/ci.yml/badge.svg)](https://github.com/carlosplanchon/rsyscall-ng/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/rsyscall-ng.svg)](https://pypi.org/project/rsyscall-ng/)
[![Python versions](https://img.shields.io/pypi/pyversions/rsyscall-ng.svg)](https://pypi.org/project/rsyscall-ng/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://github.com/carlosplanchon/rsyscall-ng/blob/main/LICENSE)
[![Platform: Linux x86_64](https://img.shields.io/badge/platform-Linux%20x86__64-blue.svg)](https://github.com/carlosplanchon/rsyscall-ng#quick-start)
[![DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/carlosplanchon/rsyscall-ng)

## What it looks like

A process object runs system calls in the process it stands for. Here that is a
child of the interpreter:

```python
import trio
from rsyscall import local_process

async def main():
    child = await local_process.fork()        # a new process, driven from this one
    # write(2) runs in the child, on a buffer allocated in the child's memory
    await child.stdout.write(await child.ptr(b"Hello from the child!\n"))
    echo = await child.environ.which("echo")  # looked up on the child's PATH
    await (await child.exec(echo.args("...now it is echo"))).check()  # execve(2), then wait

trio.run(main)
```

The same kind of object can stand for a process on another machine. Below, the
Python code runs here, while the process, its `fork` and its `execve` run on
`worker`:

```python
import trio
from rsyscall import local_process
from rsyscall.tasks.ssh import make_ssh_host

async def main():
    host = await make_ssh_host(local_process, lambda ssh: ssh.args("worker"))
    _, worker = await host.ssh(local_process)      # a process on worker, driven from here
    child = await worker.fork()                     # the fork happens on worker
    uname = await child.environ.which("uname")      # found on worker's PATH
    await (await child.exec(uname.args("-n"))).check()  # prints worker's hostname

trio.run(main)
```

`worker` is any x86_64 Linux machine you can reach with `ssh worker` that has a
POSIX shell and GNU coreutils. Nothing has to be installed there: a small static
bootstrap helper travels over the same ssh connection. The function passed to
`make_ssh_host` extends the `ssh` command line, so ssh options such as a jump
host or connection sharing can go there. `scripts/hello.py` is the first example
with more output; `make hello` and the CI run it.

## Relation to upstream

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
- [x] PEP 517 packaging: `pip install .` and `make wheel` build an abi3 wheel
      that bundles the Rust native side (`rsyscall/_native`); `make wheel-test`
      checks the installed wheel against the recorded baseline on CPython 3.12,
      3.13 and 3.14, and `make sdist-test` does the same for a wheel built from
      the sdist outside the repository
- [x] bootstrap helpers decoupled from Nix: `rsyscall.tasks.{stub,stdin_bootstrap,ssh}`
      take them from `rsyscall._native` and OpenSSH from `PATH`; `test_stub`,
      `test_stdinboot`, `test_persistent` and `test_ssh` are in the baseline, so the
      differential test covers the helper executables
- [x] continuous integration on GitHub-hosted Ubuntu 24.04 runners: crate
      tests, the differential C-vs-Rust baseline recorded on the runner, and the
      wheel and the sdist tested on CPython 3.12 to 3.14
- [ ] aarch64 (later phase)

## Layout

| Path                       | What                                                        |
|----------------------------|-------------------------------------------------------------|
| `python/`                  | upstream Python package tree (`rsyscall`, `dneio`, `arepl`, `wish`, `rsysapps`) |
| `pyproject.toml`, `setup.py`, `MANIFEST.in` | PEP 517 packaging of `python/` (setuptools + cffi); `setup.py` builds `native/` with cargo and bundles its artefacts |
| `python/rsyscall/_native/` | `rsyscall._native`: where the bundled `librsyscall.so` and helper executables live, and how to find them |
| `scripts/`                 | oracle build, venv setup, baseline runner and comparer, smoke test, wheel test, spec checks, black-box probes, CI runner setup |
| `.github/workflows/ci.yml` | the CI workflow, described under "Continuous integration" |
| `tests/baseline-c.txt`     | per-test status of the suite against the C backend          |
| `docs/spec/`               | clean-room v0 specification of the native side (wire protocol, native ABI, bootstrap handshakes, generated layouts and vectors) |
| `native/`                  | clean-room Rust reimplementation of the native side (`core/` logic and tests, `rsyscall/` cdylib and helper executables); see `native/README.md` |
| `native/prefix/` (gitignored) | the Rust native side installed by `make native` with the oracle's layout |
| `tests/baseline-rust.txt`  | the same suite recorded against the Rust backend; identical to the C one |
| `reference/` (gitignored)  | pinned upstream clone and the locally built C oracle        |
| `.venv/`, `.venv-rust/` (gitignored) | the virtualenv of each backend, created by `make venv` |
| `dist/`, `.venv-wheel/` (gitignored) | wheels and sdists from `make wheel`; the throwaway venv of `make wheel-test` |

## Quick start

Requirements: Linux x86_64, git, [uv](https://docs.astral.sh/uv/), a C compiler
(for the cffi extension), Rust 1.88 or newer with cargo (`native/` uses naked functions)
and, for the C oracle only, autotools, libtool, pkg-config and the Linux kernel
headers.

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

In this development flow `scripts/env.sh` exports `RSYSCALL_NATIVE=prefix`: the
cffi extension `rsyscall._raw` is linked through pkg-config against the selected
backend's prefix, with its rpath baked in by `make venv` (plus `LD_LIBRARY_PATH`
as a belt-and-braces measure, since both venvs share the in-tree extension), and
`RSYSCALL_LIBEXEC_DIR` points `rsyscall._native` at that prefix's helper
executables. Nothing from `native/` is copied into `python/` in this mode.

## Installing and wheels

Outside the development flow the default mode, `bundled`, applies: `setup.py`
runs `cargo build --release` in `native/`, copies `librsyscall.so` and the three
helper executables into `rsyscall/_native/` and links the extension with an
`$ORIGIN/_native` rpath, so the installed package is self-contained and needs
neither Nix nor a prefix:

```sh
uv pip install .        # or pip install .: builds native/ with cargo, nothing else to set up
make wheel              # dist/rsyscall_ng-*.whl, abi3 (CPython 3.12+), from a clean dist/
make wheel-manylinux    # check it (auditwheel, abi3audit) and retag it as manylinux_2_17 (uvx)
make wheel-test         # install the newest wheel into .venv-wheel and exercise it from /tmp:
                        # import, bundled helpers, smoke test, test-suite vs tests/baseline-rust.txt
RSYSCALL_WHEEL_PYTHON=3.12 make wheel-test   # the same on another interpreter (3.12, 3.13, 3.14)
make sdist              # source distribution: python/ plus the native/ sources and docs/spec/
make sdist-test         # unpack it outside the repository, build a wheel as pip would
                        # (isolated PEP 517 build, cargo included) and test it like wheel-test
```

The wheel is tagged `cp312-abi3`: the cffi extension uses only the stable ABI
(`abi3audit` finds no violation), so one wheel serves every CPython from 3.12 on.
Both the wheel and a wheel built from the sdist give the recorded baseline's
per-test results on 3.12, 3.13 and 3.14. Building from the sdist needs, on the
installing machine, cargo with Rust 1.88 or newer (the first release with naked
functions; 1.87 fails), a C compiler and the Python headers (`python3-dev` on
Debian and Ubuntu).

`rsyscall._native.helper(name)` returns the path of a bundled helper executable
(or of the one under `RSYSCALL_LIBEXEC_DIR`, when set) and `library_path()` the
bundled `librsyscall.so`, or `None` when the extension was linked against a
prefix. Wheels bundle only artefacts built from `native/`; the upstream C is
never packaged.

## Running tests

```sh
make test PYTEST_ARGS='-k clone'          # any pytest arguments
RSYSCALL_TEST_OPTIONAL=1 make test        # collect even the modules whose environment is missing
```

Modules are ignored at collection time only when what they need is missing on
this machine: a Nix store (`test_nix.py`); `ssh`, `sshd` and `ssh-keygen` on
`PATH` or in `/usr/sbin`, `/usr/local/sbin`, `/sbin` (`test_ssh.py`,
`test_persistent.py`); `/dev/fuse` (`test_fuse.py`); `pyroute2` and
`/dev/net/tun` (`test_net.py`). `RSYSCALL_TEST_OPTIONAL=1` collects them
regardless, and the fourth header line of a baseline records what was ignored
and why. The baseline records the status of every collected test; it is a
description of reality, not a promise that everything passes. `make baseline`
runs every test in its own interpreter: the tests share the module-level
`rsyscall.local_process`, whose state does not survive a test being killed by
the timeout, so in a single process one hanging test would poison the rest.
Tests also leave processes behind (they share the interpreter's memory and hold
both ends of their syscall sockets), so `make baseline` and `make wheel-test`
run each pytest in a session of its own and kill its whole process group
afterwards (`scripts/pytest_session.py`).

## Continuous integration

`.github/workflows/ci.yml` runs on pushes to `main`, on pull requests, weekly
and on demand, on GitHub-hosted Ubuntu 24.04 runners. `scripts/ci-setup.sh`
installs autotools and the OpenSSH server and lifts Ubuntu's AppArmor
restriction on unprivileged user namespaces, which the test-suite creates.

- **differential** runs the crate tests, builds the Rust native side with its
  ELF checks and the C oracle, runs the specification checks and the smoke
  tests, and records both baselines on the runner. It fails unless the two are
  identical. Differences from the committed baselines are only warnings,
  because a few tests depend on the machine; the recorded baselines and the
  per-test logs are uploaded as artifacts.
- **dist** builds the manylinux abi3 wheel, checked by auditwheel and
  abi3audit, and the sdist, and uploads them as the `dist` artifact.
- **test-dist** installs the wheel on CPython 3.12, 3.13 and 3.14, and a wheel
  built from the sdist, and compares each one's per-test results with the Rust
  baseline recorded by the differential job.

Actions are pinned to commit SHAs, with the release named in a comment.

## Licensing

New code, including all of `native/`, is MIT, Copyright (c) 2026 Carlos Andrés
Planchón Prestes (see `LICENSE`). `python/` is MIT per upstream package
metadata, Copyright 2018-2022 Spencer Baugh and contributors. Upstream `c/` is
intentionally not part of this repository; `native/` was written from
`docs/spec/` alone, without access to it. See `NOTICE` for details.
