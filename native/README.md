# rsyscall-ng native side (Rust, clean-room)

This directory is the clean-room Rust reimplementation of the native side of
rsyscall: the C-ABI library `librsyscall.so` (the five symbols the Python client
loads through the cffi module `rsyscall._raw`) and the three helper executables
`rsyscall-bootstrap`, `rsyscall-stdin-bootstrap` and `rsyscall-unix-stub`. It is
byte-compatible with v0 of `docs/spec` and is a drop-in replacement for the
upstream C implementation: the same Python package, unchanged, runs against either
(`BACKEND=c` or `BACKEND=rust` in the Makefile), and the pytest suite produces the
same baseline against both.

Only x86-64 Linux is supported (native-abi.md §1).

## Layout

```
native/
  Cargo.toml              workspace (resolver 3); release profile: lto = "fat",
                          codegen-units = 1, panic = "abort", strip = "debuginfo"
  core/                   crate rsyscall-core: #![no_std] rlib, no #[panic_handler],
                          no mem* symbols (so it links into std test binaries)
    src/arch/x86_64.rs      define_raw_syscall!, define_trampoline!, define_futex_helper!
                            (naked functions, core::arch::naked_asm!) and the internal
                            instantiations raw_syscall7 / trampoline / futex_helper
    src/sys/consts.rs       syscall numbers, flags, errnos (each with a `// source:`)
    src/sys/mod.rs          raw syscall wrappers; #[repr(C)] Iovec, Msghdr, Cmsghdr,
                            SockaddrUn, RobustList, FutexNode
    src/io.rs               read_exact / write_all (sendto MSG_NOSIGNAL, write fallback)
    src/wire.rs             Request (56 bytes) and response (8 bytes) codec; TrampolineStack
    src/server.rs           serve(infd, outfd): the syscall loop
    src/persistent.rs       serve_persistent: disconnect, accept, reconnection handshake
    src/cmsg.rs             SCM_RIGHTS control data: parse_control, recv_fds, send_fds
    src/describe.rs         SymbolTable, Bootstrap, StdinBootstrap, UnixStub;
                            length-prefixed strings; environment
    src/cstr.rs             argv/envp walking, env lookup, decimal formatting, basename
    src/diag.rs             one-line stderr diagnostics without core::fmt
    tests/                  vectors.rs, server.rs, clone_asm.rs, consts.rs,
                            persistent.rs, cstr.rs (22 test functions)
  rsyscall/               crate rsyscall-native: the artefacts
    build.rs                linker flags (-z now, -Bsymbolic, -z defs, -nostdlib, ...
                            for the cdylib; -static -no-pie -e _start for the bins)
    src/lib.rs              cdylib root: rt/mem.rs + rt/panic.rs + rt/exports.rs
    src/rt/exports.rs       the five #[unsafe(no_mangle)] extern "C" symbols and
                            symbol_table(); shared by the cdylib and the bins
    src/rt/mem.rs           memcpy/memmove/memset/memcmp/bcmp/strlen (global_asm!, weak)
    src/rt/panic.rs         #[panic_handler] -> exit_group(127)
    src/rt/start.rs         _start for the static executables
    src/bin/bootstrap.rs        rsyscall-bootstrap        (ssh bootstrap)
    src/bin/stdin_bootstrap.rs  rsyscall-stdin-bootstrap
    src/bin/unix_stub.rs        rsyscall-unix-stub
    include/rsyscall.h      the C header: the six structs and five prototypes
    rsyscall.pc.in          pkg-config template (@PREFIX@)
  prefix/                 install tree written by `make native`
                          (lib/, include/, lib/pkgconfig/, libexec/rsyscall/)
```

Where each symbol lives: `rsyscall_raw_syscall`, `rsyscall_trampoline` and
`rsyscall_futex_helper` are the macros of `core/src/arch/x86_64.rs`, instantiated
under the exported names in `rsyscall/src/rt/exports.rs`; `rsyscall_server` is a
thin `extern "C"` wrapper (same file) around `core/src/server.rs`;
`rsyscall_persistent_server` wraps `core/src/persistent.rs` and terminates the
process with `exit_group(1)` if the persistent loop ever returns. Internal calls
always go to the mangled core functions, never through the exported (interposable)
names. Each executable includes `rt/exports.rs` too, so the addresses it reports in
its describe struct are those of real `extern "C"` entry points in its own image
(native-abi.md §8).

## Build, test, use

From the repository root:

| command | what it does |
|---|---|
| `make native` | `cargo build --release -p rsyscall-native`, installs into `native/prefix` with the oracle's layout and runs the ELF checks of `scripts/native-install.sh` (exactly five exported symbols, no undefined symbols, BIND_NOW, no TLS/INTERP, static ET_EXEC executables, pkg-config resolves) |
| `make native-test` | `cargo test -p rsyscall-core` (the 22 tests) |
| `make venv BACKEND=rust` | builds the cffi module against `native/prefix` into `.venv-rust` |
| `make hello BACKEND=rust` | the smoke test: clone a process, write to its stdout, exec |
| `make baseline BACKEND=rust && make baseline-diff` | the pytest suite, one interpreter per test, compared with the C baseline |
| `make probe-diff` | the black-box probes of the helper executables against both backends, normalised and diffed (outputs under `reference/probe-compare/`) |
| `python3 scripts/header-check.py` | checks `include/rsyscall.h` against the cffi cdef (35 offsets, 6 sizes, 5 prototypes) |

Plain cargo equivalents (all with `--manifest-path native/Cargo.toml`):
`cargo build --release -p rsyscall-native`, `cargo test -p rsyscall-core`,
`cargo doc --no-deps -p rsyscall-core`. The workspace targets only
`x86_64-unknown-linux-gnu` with the system toolchain (rustc 1.98, edition 2024,
gcc as the linker driver); it has no runtime dependencies. The only external
crates are dev-dependencies of the tests (`serde`/`serde_json` to read
`docs/spec/vectors/v0.json`, `linux-raw-sys` to cross-check constants).

## Conformance

| symbol / executable | specification | source | verified by |
|---|---|---|---|
| `rsyscall_raw_syscall` | native-abi.md §3.1 | `core/src/arch/x86_64.rs` (`define_raw_syscall!`), `rsyscall/src/rt/exports.rs` | `objdump` listing below; `tests/clone_asm.rs` issues `clone`, `wait4`, `kill`, `futex` through it; `make hello` |
| `rsyscall_trampoline` | native-abi.md §3.5, §4 | `define_trampoline!`, `exports.rs` | listing below; `tests/clone_asm.rs` (a cloned child enters a target and exits with its status); `tests/vectors.rs` (`stack_image`, `trampoline_stack`) |
| `rsyscall_futex_helper` | native-abi.md §3.4, §6 | `define_futex_helper!`, `exports.rs` | listing below; `tests/clone_asm.rs` (stops with SIGSTOP, waits, exits 0 when the word changes); `make hello` |
| `rsyscall_server` | native-abi.md §3.2; wire-protocol.md §1–§10 | `core/src/server.rs`, `core/src/io.rs`, `core/src/wire.rs` | `tests/server.rs` (exact 56-byte reads, fragmentation, pipelining, memory write/read, `-errno` passthrough, EOF, SIGPIPE safety); `tests/vectors.rs`; `make hello`; the baseline |
| `rsyscall_persistent_server` | native-abi.md §3.3; wire-protocol.md §10; bootstrap-handshakes.md §5 | `core/src/persistent.rs`, `core/src/cmsg.rs` | `tests/persistent.rs` (SHUT_WR, shutdown-not-close, reconnection with count 2, failures with count 1 and 3, path never unlinked); `tests/vectors.rs` (`persistent_count`, `persistent_reply`, `scm_rights_*`); `scripts/probes/probe_persistent.py` |
| `rsyscall-bootstrap` | bootstrap-handshakes.md §2, §6 | `rsyscall/src/bin/bootstrap.rs` | `make probe-diff` (mode `bootstrap`); the §6 failure runs |
| `rsyscall-stdin-bootstrap` | bootstrap-handshakes.md §3, §6 | `rsyscall/src/bin/stdin_bootstrap.rs` | `make probe-diff` (mode `stdin`); the §6 failure runs. (`python/rsyscall/tests/test_stdinboot.py` is not part of the baseline: it is excluded until the Nix coupling is removed, see `tests/baseline-notes.md`) |
| `rsyscall-unix-stub` | bootstrap-handshakes.md §4, §6 | `rsyscall/src/bin/unix_stub.rs` | `make probe-diff` (modes `stub`, `stublong` with a 133-byte path); the §6 failure runs. (`python/rsyscall/tests/test_stub.py` is likewise excluded from the baseline for now) |
| describe structs, strings, environment | bootstrap-handshakes.md §0; native-abi.md §8; abi-layouts.generated.md | `core/src/describe.rs`, `core/src/cstr.rs` | `tests/vectors.rs` (`describe_*`, `lp_string`, `sigmask_sigchld`, sizes 32/56/64/80 and offsets); `tests/cstr.rs` |
| `include/rsyscall.h` | native-abi.md §2 | `rsyscall/include/rsyscall.h` | `make venv BACKEND=rust` (cffi API mode checks the six struct definitions and five symbols); `scripts/header-check.py` |
| constants | native-abi.md, wire-protocol.md, vectors `clone_args` | `core/src/sys/consts.rs` | `tests/consts.rs` (cross-check against `linux-raw-sys`) |

## Freestanding properties and how to verify them

`librsyscall.so` and the executables contain no libc, no TLS and no dynamic
dependencies (native-abi.md §9). On the installed artefacts:

```sh
so=native/prefix/lib/librsyscall.so
nm -D --defined-only $so          # exactly: rsyscall_futex_helper rsyscall_persistent_server
                                  #          rsyscall_raw_syscall rsyscall_server rsyscall_trampoline
nm -D --undefined-only $so        # empty
readelf -d $so                    # FLAGS: SYMBOLIC BIND_NOW; FLAGS_1: NOW; SONAME librsyscall.so; no NEEDED
readelf -lW $so                   # no TLS and no INTERP program header
readelf -r $so | grep -c JUMP_SLOT   # 0: nothing is bound lazily
objdump -d -M intel $so | grep -oE 'sub +rsp,0x[0-9a-f]+' | sort -u   # largest frame 0x138 (312 bytes)
objdump -d -M intel $so | grep -E 'call' | grep '@plt'               # empty: no PLT calls
for x in native/prefix/libexec/rsyscall/*; do readelf -h $x | grep Type; readelf -lW $x | grep -E 'INTERP|DYNAMIC|TLS'; done
                                  # Type: EXEC; no INTERP/DYNAMIC/TLS
```

The stack budget of trampoline-entered code is 4096 bytes minus the 64-byte image
with no guard page (native-abi.md §4); the largest frame in the library is the
reconnection handshake's 0x138 bytes.

The three assembly exports read as specified (`objdump -d --disassemble=<name> -M intel $so`):

```
rsyscall_raw_syscall:                    rsyscall_trampoline:
  mov    rax,QWORD PTR [rsp+0x8]           pop    rdi
  mov    r10,rcx                           pop    rsi
  syscall                                  pop    rdx
  ret                                      pop    rcx
                                           pop    r8
rsyscall_futex_helper:                     pop    r9
  mov    rbx,rdi                           pop    rax
  mov    r12,rsi                           call   rax
  mov    eax,0xba        ; gettid          movzx  edi,al
  syscall                                  mov    eax,0xe7    ; exit_group
  mov    edi,eax                           syscall
  mov    esi,0x13        ; SIGSTOP         ud2
  mov    eax,0xc8        ; tkill
  syscall
2:mov    eax,DWORD PTR [rbx]
  cmp    eax,r12d
  jne    3f
  mov    rdi,rbx
  xor    esi,esi         ; FUTEX_WAIT
  mov    edx,r12d
  xor    r10d,r10d       ; timeout NULL
  mov    eax,0xca        ; futex
  syscall
  test   rax,rax
  je     2b
  cmp    rax,-4          ; -EINTR
  je     2b
3:xor    edi,edi
  mov    eax,0xe7        ; exit_group(0)
  syscall
  ud2
```

## Behaviour left unspecified in v0 and the choices made here

| where | Unspecified in v0 | choice (the spec's Recommended default unless noted) |
|---|---|---|
| wire-protocol.md §1 | stream types other than an `AF_UNIX` stream socket | any blocking byte stream: `sendto` with `MSG_NOSIGNAL`, falling back to `write` on `ENOTSOCK` |
| native-abi.md §3.2 | return value of `rsyscall_server` | 0 on EOF, 1 on a read error, 2 on a write error |
| native-abi.md §3.3 | `accept` failure in the persistent server | `serve_persistent` returns non-zero and the export calls `exit_group(1)`; `EINTR`/`ECONNABORTED` are retried |
| native-abi.md §3.4 | `EINTR` and a wake with the word unchanged in the futex helper; its exit status | re-read the word and wait again while it still equals `expected`; `exit_group(0)` |
| native-abi.md §3.5 | `call` vs `push`+`jmp`; exit status after the target returns | `call rax`; `exit_group(ret & 0xff)` |
| wire-protocol.md §10 | exit status of a plain server process after EOF; SIGPIPE | `serve` returns 0, so the trampoline calls `exit_group(0)`; every response is sent with `MSG_NOSIGNAL` |
| bootstrap-handshakes.md §0 | `FD_CLOEXEC` on received fds | received with `MSG_CMSG_CLOEXEC` |
| bootstrap-handshakes.md §2 | the hand-off from `socket` mode to `rsyscall` mode | a second listening socket `pass` next to `data`; one connection, `SCM_RIGHTS` with the `data` listening fd, `pass` unlinked once the connection is accepted |
| bootstrap-handshakes.md §3 | extra arguments; `futex_memfd` | ignored; `-1` |
| bootstrap-handshakes.md §4 | paths longer than 107 bytes; closing the stub's own connection; the `RSYSCALL_UNIX_STUB_SOCK_PATH` entry | `openat(AT_FDCWD, path, O_PATH\|O_CLOEXEC)` and `connect` to `/proc/self/fd/<n>`; the connection (and the O_PATH fd) are closed after the handshake; the entry is not stripped |
| bootstrap-handshakes.md §5 | the old connection on disconnect; a `count` that does not match the fds received | `shutdown(SHUT_RDWR)` on `infd` and `outfd`, the fds are left to the client's garbage collection; the received fds and the connection are closed and the server keeps listening (also for `count < 1`, `count > 16`, a truncated message or one that is not exactly one `SCM_RIGHTS` control message) |
| bootstrap-handshakes.md §6 | reporting a failed handshake; exit status after EOF of the syscall socket | `<program>: <message>[: <errno text>]` on stderr, exit 1, nothing on stdout; exit 0 for all three executables |

Implementation limits: at most 16 fds in one `SCM_RIGHTS` message (`cmsg::MAX_FDS`;
the client passes at most 4); the errno texts of `diag.rs` cover the common cases
and print `Unknown error <n>` otherwise.

## Differences from the upstream C oracle's observed behaviour

Each of these is permitted by the specification (citations in parentheses); they
are the residual lines of `make probe-diff` and `scripts/probes/probe_persistent.py`.

1. `rsyscall-stdin-bootstrap` reports `futex_memfd = -1`; the oracle reports 0
   (bootstrap-handshakes.md §3: Unspecified, Recommended default -1; the client never
   reads the field).
2. Persistent reconnection with a bad count: for `count = 1` with two fds the server
   replies nothing, closes the received fds and the connection and keeps listening,
   where the oracle replied one number and kept serving; for `count = 3` with two fds
   the same, where the oracle printed `Message has wrong controllen` and exited 1
   (bootstrap-handshakes.md §5: Unspecified, Recommended default).
3. `rsyscall-bootstrap rsyscall` exits 0 with nothing on stderr when the syscall
   socket reaches EOF; the oracle exits 1 with
   `rsyscall-bootstrap: rsyscall_server(syscall_sock, syscall_sock): Success`
   (bootstrap-handshakes.md §6: only waited for, never checked; Recommended default 0).
4. The `pass` connection (after the two accepts), the O_PATH fd (after the handshake)
   and the stub's connection socket are closed; the oracle keeps all three open
   (bootstrap-handshakes.md §2: hand-off implementation-defined; §4: closing the
   connection is the Recommended default). Consequences visible in the probes: those
   fds are absent from the fd tables, a later `accept4` requested through the wire
   returns the freed number, and for a path of at most 107 bytes the stub connects
   with a plain `sockaddr_un` (the oracle always goes through O_PATH), so its four
   received fds are numbered one lower.
5. `rsyscall-bootstrap socket` keeps stdout open after `done\n`; the oracle closes it
   (bootstrap-handshakes.md §2 only forbids writing to stdout after `done\n`).
6. The listening socket handed over on `pass` is received with `MSG_CMSG_CLOEXEC`
   and therefore carries `FD_CLOEXEC`; the oracle's does not (bootstrap-handshakes.md
   §0: Unspecified, Recommended default).
7. The futex helper and the trampoline terminate with `exit_group`; the oracle was
   observed using `exit` (native-abi.md §3.4, §3.5: either).
8. Diagnostic wording: `connect(pass): No such file or directory` and
   `connect(<path>): No such file or directory` where the oracle printed
   `bind: No such file or directory`; `missing environment variable
   RSYSCALL_UNIX_STUB_SOCK_PATH` without the oracle's trailing `: Success`; the other
   quoted messages (`usage: <path> <type>`, `unknown type <arg>`, `recvmsg(sock=0):
   Socket operation on non-socket`) are reproduced verbatim (bootstrap-handshakes.md
   §6: Unspecified).
9. Unknown errno values print `Unknown error <n>`.
10. `rsyscall-bootstrap rsyscall` does not call `readlinkat("/proc/self/exe")` or
    `prctl(PR_SET_PDEATHSIG)` as the oracle does (bootstrap-handshakes.md §2
    Rationale: not required).

## Not verified

- A real ssh transport (an actual `sshd`) for `rsyscall-bootstrap`: only the
  two-stage black-box probe (`make probe-diff`, mode `bootstrap`) was run.
- Error paths that were not driven: `recvmsg` with the wrong fd count, EOF or a
  malformed message in the executables; `write` failures on the data socket; `bind`,
  `listen`, `accept` and `sendmsg` failures in `rsyscall-bootstrap`; the fatal
  `accept4` error path of the persistent server (return non-zero, `exit_group(1)`)
  and its `ECONNABORTED` retry; `rsyscall-stdin-bootstrap` with extra arguments.
- `MSG_CTRUNC` at run time (it needs more than 16 fds); the control-data parser is
  covered at unit level only.
- `tests/persistent.rs` runs the persistent server in a thread of the test process,
  not in a cloned child on a 4 KiB stack; the stack budget is checked statically
  (largest frame 0x138) and the real cloned persistent child is exercised by
  `scripts/probes/probe_persistent.py`.
- The SIGPIPE scenario of `tests/server.rs` accepts a return value of 2 or 0 (the
  peer may close before or after the response is written); it runs with `SIGPIPE`
  set to `SIG_DFL`, so a missing `MSG_NOSIGNAL` would kill the test process.

## Clean-room statement

Written on 2026-09-29. The Rust code, the header, the build glue under `native/`
and this file were implemented by an agent whose read access was restricted to
`docs/spec/**`, the repository's tooling files (`Makefile`, `pytest.ini`,
`scripts/**`, `tests/baseline-*.txt`, `tests/baseline-notes.md`, `README.md`,
`NOTICE`) and the official documentation of Rust, Cargo and the crates used. It
never read anything under `reference/` (the third-party native implementation),
except the probe outputs that `make probe-diff` writes under
`reference/probe-compare/`; nor anything under `.venv*/`; nor any file ending in
`.c`, `.h` or `.S` (system headers included); nor anything under `python/`. `nm`,
`readelf`, `objdump` and `strace` were used only on artefacts it built itself. The
upstream implementation's behaviour was observed only through the black-box probe
drivers in `scripts/probes/` and the differential pytest baseline. No forbidden
content was exposed at any point. The only incidents were two tool-permission
denials during the first milestone, for a `cat` of an internal copy of a tool
result (not pursued) and for a `cat` of `docs/spec/vectors/v0.json` (an allowed
specification file, subsequently read with the ordinary file reader).

The reviewer, who had read the upstream C implementation earlier for an unrelated
analysis, authored none of the Rust and reviewed the work against `docs/spec` only.
