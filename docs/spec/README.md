# rsyscall-ng native-side specification (v0)

## 1. Purpose and status

This directory specifies the native side of rsyscall: the C-ABI library loaded through the cffi
module `rsyscall._raw` (five symbols) and the three helper executables the Python client starts
(`rsyscall-bootstrap`, `rsyscall-stdin-bootstrap`, `rsyscall-unix-stub`). It is the only input the
Rust reimplementation receives, so it is written to be complete, precise and derived exclusively
from the MIT-licensed Python side in `python/`.

- Version: **v0**, defined as the protocol exactly as the Python client implements it today. A v0
  implementation is byte-compatible with the current client, so the existing test-suite works as
  a differential oracle.
- Upstream import: the Python tree comes from upstream commit
  `2a362099610a664caeb7f06dd805e5a0fb80cd08` (see `NOTICE`); citations refer to the tree at the
  repository commit that adds this specification.
- Oracle: `tests/baseline-c.txt`, the recorded outcome of the suite against the upstream C
  implementation (`tests/baseline-notes.md` explains how it was recorded). A conforming
  implementation reproduces that outcome for every test that exercises the native side.

## 2. Scope

In scope: the wire protocol between client and server (`wire-protocol.md`); the ABI of the five
symbols, the stack image, the `clone` arguments, the futex EOF mechanism and the constraints on
trampoline-entered code (`native-abi.md`); the handshakes of the three helper executables and of
the persistent server (`bootstrap-handshakes.md`); the exact struct layouts
(`abi-layouts.generated.md`) and byte vectors (`vectors/v0.json`).

Out of scope:

- an `rsyscall-server` executable: nothing in `python/` starts one (the oracle build script merely
  checks that upstream ships it);
- any architecture other than x86-64 LP64 little-endian (`native-abi.md` §1;
  `evolution-notes.md` sketches an aarch64 mapping);
- Python-side bugs: they are listed in `evolution-notes.md` and left as they are, because v0 is the
  client as it exists;
- the build system and packaging of the Rust crate, beyond the pkg-config and header contract of
  `native-abi.md` §2.

## 3. Conventions and terms

RFC 2119 keywords (MUST, MUST NOT, SHOULD, SHOULD NOT, MAY) are used in the three normative files
only. Every paragraph or table row containing one of them carries at least one citation into
`python/` (§5). Non-normative material inside the normative files appears only in paragraphs
starting with `Rationale:` or `Python-side behaviour:`. Where the Python side leaves a choice open,
the text says **Unspecified in v0** and gives a `Recommended default:`; black-box observations of
the upstream implementation (§4) may confirm a default but never make it normative.

Terms used throughout:

| term | meaning |
|---|---|
| client | the Python process running the `rsyscall` package |
| server | the native syscall loop (`rsyscall_server` or `rsyscall_persistent_server`) running in another process |
| syscall socket | the stream the server reads requests from and writes responses to; `server_fd` on the server side |
| data socket | the second stream of a bootstrap, carrying the describe struct and strings; unused afterwards |
| access side / remote side | the two ends of a channel: the client's end (non-blocking, registered on the client's epoll) and the end that lives in the server process (blocking) |
| describe struct | the fixed-layout struct (`rsyscall_bootstrap`, `rsyscall_stdin_bootstrap`, `rsyscall_unix_stub`) a helper executable writes on the data socket |
| stack image | the 64 bytes at the top of the stack passed to `clone`: the trampoline address and `struct rsyscall_trampoline_stack` |
| helper executable | one of `rsyscall-bootstrap`, `rsyscall-stdin-bootstrap`, `rsyscall-unix-stub` |
| oracle | the unmodified upstream C implementation built under `reference/prefix`, used only as a black box |

Hex dumps are little-endian, one byte per token, grouped by field. Tables are preferred to prose.
The provenance map (`provenance-map.md`) is the catalogue of where `python/` establishes each
fact; this specification cites `python/` directly rather than the map.

## 4. Clean-room process statement

Written on 2026-09-29 by an agent whose read access was restricted to `python/`, `docs/`,
`scripts/`, `tests/` and the top-level files (`README.md`, `NOTICE`, `LICENSE`, `Makefile`,
`pytest.ini`, `.gitignore`). The agent did not open, list, grep or read anything under
`reference/` (which holds the third-party native implementation), did not read anything under
`.venv/` as source, did not read any file ending in `.c`, `.h` or `.S`, and did not disassemble or
dump any binary. No forbidden content was exposed accidentally during the work. The only
third-party documentation consulted was the cffi documentation (through the Context7 service) for
the cffi facts stated in `native-abi.md` §2, each marked with its source there.

Every normative statement is derived from `python/`. The following black-box executions of the
oracle were performed in addition, purely to observe behaviour; each fact learned this way is
labelled `Observed (black-box)` inside a `Rationale:` paragraph of the normative files and only
ever settles something `python/` leaves open:

1. `make hello` (the repository smoke test). Output: `Hello world from a cloned rsyscall process!`,
   `hello from exec, via rsyscall`, the child task line, and
   `ChildState(code=CLD.EXITED, ..., exit_status=0)`.
2. The strace log of the same smoke test produced beforehand by the requester with
   `strace -f -x -s 64 -e trace=read,recvfrom,write,sendto,sendmsg,recvmsg,clone,clone3,futex,kill,tgkill,tkill,exit,exit_group,shutdown -o hello.strace .venv/bin/python scripts/hello.py`
   was read as observed data. It showed: the two `clone` calls and their flags and `child_tidptr`
   (`native-abi.md` §5); the helper's `tkill(self, SIGSTOP)`, the client's `kill(pid, SIGCONT)`,
   `futex(addr, FUTEX_WAIT, 1, NULL) = 0` and `exit(0)` (`native-abi.md` §3.4); the server reading
   requests as `read(fd, buf, 56)`, executing `recvfrom(..., MSG_WAITALL)` for memory writes and
   writing 8-byte responses; the client reading 70 pipelined responses in one `read`
   (`wire-protocol.md` §8); the cloned child's first syscall being the first request read.
3. Each helper executable run by path with no arguments, `env -i` and `</dev/null`:
   `env -i reference/prefix/libexec/rsyscall/rsyscall-bootstrap </dev/null` (usage message,
   exit 1), `env -i reference/prefix/libexec/rsyscall/rsyscall-stdin-bootstrap </dev/null`
   (`recvmsg(sock=0): Socket operation on non-socket`, exit 1),
   `env -i reference/prefix/libexec/rsyscall/rsyscall-unix-stub </dev/null`
   (`missing environment variable RSYSCALL_UNIX_STUB_SOCK_PATH`, exit 1). Also
   `env -i reference/prefix/libexec/rsyscall/rsyscall-bootstrap rsyscall </dev/null` in an empty
   temporary directory (`bind: No such file or directory`, exit 1),
   `env -i reference/prefix/libexec/rsyscall/rsyscall-bootstrap bogus </dev/null`
   (`unknown type bogus`, exit 1) and
   `env -i RSYSCALL_UNIX_STUB_SOCK_PATH=<tmpdir>/nope.sock reference/prefix/libexec/rsyscall/rsyscall-unix-stub a b </dev/null`
   (`bind: No such file or directory`, exit 1). See `bootstrap-handshakes.md` §6.
4. A standard-library-only driver, `probe_oracle.py` (committed as
   `scripts/probes/probe_oracle.py`), run as
   `strace -f -x -s 80 -o probe_<mode>.strace -e trace=%network,%process,read,write,close,dup2,dup3,rt_sigprocmask,shutdown,unlink,unlinkat,openat,fcntl,exit,exit_group,futex,tkill,kill,prctl,readlink,readlinkat,chdir python3 probe_oracle.py reference/prefix/libexec/rsyscall <mode>`
   for `<mode>` in `stdin`, `stub`, `stublong`, `bootstrap` (and once without strace). The driver
   reproduces the client's handshakes with `socket`/`struct`/`array` only: for `stdin` it starts
   the executable with a `socketpair` end as fd 0 and `SIGUSR1` blocked, sends one 1-byte
   `sendmsg` with three fds, reads the 64-byte struct and the strings; for `stub` and `stublong`
   (a 133-byte socket path bound through `/proc/self/fd/<O_PATH dirfd>/`) it listens, starts the
   executable with `RSYSCALL_UNIX_STUB_SOCK_PATH` set and argv `dummy_stub arg1 'arg two' ''`,
   accepts, sends four fds (the third a memfd), reads the 80-byte struct, argv and envp; for
   `bootstrap` it runs `rsyscall-bootstrap socket` in a temporary directory, reads `done`, lists
   the directory, runs `rsyscall-bootstrap rsyscall` there, waits for the `socket` process, connects
   twice to `<dir>/data` and reads the 56-byte struct and envp. In every mode it then speaks the
   wire protocol on the syscall socket (`getpid`, `mmap`, a memory write with `recvfrom`
   `MSG_WAITALL`, a memory read with `sendto`, `close(-1)`, `openat(-100, ...)`, a request sent in
   pieces of 10/30/16 bytes, two pipelined requests), inspects `/proc/<pid>/fd`,
   `/proc/<pid>/fdinfo` and `SigBlk`, and finally shuts the syscall socket down and reports the
   exit status. Observations are quoted in `wire-protocol.md` §3 and `bootstrap-handshakes.md`
   §0, §2, §3, §4 and §6.
5. A venv driver, `probe_persistent3.py` (committed as `scripts/probes/probe_persistent.py`; the
   earlier version `probe_persistent.py` is not kept), run as
   `bash -c 'source scripts/env.sh && strace -f -x -s 80 -o probe_persistent3.strace -e trace=%network,clone,clone3,read,write,close,exit,exit_group,futex,tkill,kill,unshare,unlink,unlinkat "$PY" -u probe_persistent3.py'`
   (the first version also traced `wait4,waitid`). They use the client library to `fork` a child,
   call `getpid`, then `close_interface()` and `waitpid` (plain-server EOF behaviour), and to
   create a persistent process with `clone_persistent`, `prep_for_reconnect` and `reconnect`;
   afterwards they use raw standard-library sockets to perform reconnection handshakes with
   `count` 2, 1 and 3 against two passed fds, to speak the wire protocol on the resulting fd, to
   send an `exit(0)` request, and to check the socket path and a final `connect`. An intermediate
   run (`probe_persistent2.strace`) stalled because the driver called `reconnect` after shutting
   the connection down manually, which blocks in the client's fd-table GC by design
   (`python/rsyscall/tasks/persistent.py:10`); it produced no observation. Observations are quoted
   in `wire-protocol.md` §10, `native-abi.md` §3.5 and `bootstrap-handshakes.md` §5.
6. Not an observation of the native side: a self-written cffi module (a cdef `void (*const f3)(void);`
   bound to a plain C definition) was compiled and imported with the system `python3` to check
   how cffi binds `const` function-pointer declarations; see `native-abi.md` §2.

No test-suite subset was run beyond `make hello`; the recorded baseline (`tests/baseline-c.txt`)
was used as the description of the oracle's outcome.

Review: on 2026-09-29 the text was reviewed by the session assistant, who had read the upstream C
implementation earlier in the session for an unrelated analysis and for that reason authored none
of the specification. The review compared statements against `python/` only (about thirty cited
line ranges opened and checked), audited the writer's tool log for accesses to `reference/`,
`.venv/` sources or `.c`/`.h`/`.S` files (none found; the only occurrences were the rules quoted in
the writer's instructions), re-ran `make spec-check`, and made two wording changes in
`bootstrap-handshakes.md` §2 and §3 (an RFC keyword, and the handling of extra arguments to
`rsyscall-stdin-bootstrap`, now Unspecified in v0). The reviewer's own black-box runs, `strace` of
`scripts/hello.py` (the log the writer used) and `scripts/probes/probe_eof.py` (a client
`shutdown(SHUT_RDWR)` followed by `waitpid`, showing `read(fd, "", 56) = 0` then `exit(0)`), agree
with the observations above.

## 5. Citations and generated files

A citation `python/<file>:<line>` or `python/<file>:<a>-<b>` points at the lines of the Python
client that establish the statement; line numbers refer to the current tree and are validated by
`scripts/spec-lint.py`, which also checks that every paragraph or table row containing an RFC
keyword in the normative files carries a citation, and that the non-normative files
(`evolution-notes.md`, `provenance-map.md`) contain no upper-case RFC keyword outside backticks or
quotes.

Two files are generated and never edited by hand:

- `abi-layouts.generated.md` is produced by `scripts/abi-layouts.py`, which parses
  `python/ffibuilder.py` with the `ast` module, takes the struct definitions from the string
  arguments of the `ffibuilder.cdef(...)` calls (never from the C preamble), feeds them to a
  fresh `cffi.FFI()` in ABI mode with the prelude `typedef int pid_t;` and a complete mirror of
  `struct cmsghdr`, and prints scalar sizes, one table per struct with explicit padding rows and
  the source line range, and the derived constants. It runs with the plain system `python3`
  (cffi installed) and with the venv python; `--check FILE` exits non-zero if the file differs.
- `vectors/v0.json` is produced by `scripts/spec-vectors.py`. Its `--pure` mode uses only
  `struct.pack` and the layouts; the default mode additionally imports the client classes from the
  venv (`RsyscallSyscall`, `SyscallResponse`, `Trampoline`, `TrampolineSerializer`, `Stack`,
  `FutexNode`, `Int32`, `StructList`, `CmsgList`, `CmsgSCMRights`, `Sigset`) and asserts byte
  equality, and reads the describe vectors back with `ffi.cast` field by field, which mirrors
  how the client reads them. Each vector has `name`, `hex` (bytes separated by spaces, fields by
  ` | `), `meaning`, `derived_from` (citations) and `generator`; the `clone_args` vector describes
  syscall arguments rather than bytes, so its `hex` is `null` and the values are under `json`.

`make spec-check` runs `scripts/abi-layouts.py --check` and `scripts/spec-vectors.py --check` with
the venv python (cffi, and the client classes for the vectors) and `scripts/spec-lint.py`. The
layout check ignores the cffi release named in the generated file's header.

## 6. Index, reading order and open questions

Reading order: this file, then `wire-protocol.md`, `native-abi.md`, `bootstrap-handshakes.md`,
with `abi-layouts.generated.md` and `vectors/v0.json` at hand; `evolution-notes.md` last.

| file | status | content |
|---|---|---|
| `README.md` | index | purpose, scope, terms, process, how to read |
| `wire-protocol.md` | normative | transport, request, server loop, response, memory write/read, barrier, ordering, activity fd, termination, vectors |
| `native-abi.md` | normative | platform, build contract, the five symbols, stack image, `clone`, futex EOF mechanism, memory model, symbol table, freestanding constraints |
| `bootstrap-handshakes.md` | normative | common encodings, in-process clone, ssh, stdin, unix stub, persistent server, failure conventions |
| `abi-layouts.generated.md` | generated | struct layouts and derived constants |
| `vectors/v0.json` | generated | byte-exact conformance vectors |
| `evolution-notes.md` | non-normative | candidate changes, Python-side defects, oracle gaps |
| `provenance-map.md` | input | catalogue of where `python/` establishes each fact |

The 15 open questions of `provenance-map.md` are resolved (or explicitly left unspecified with a
recommended default) here:

| # | question | resolved in |
|---|---|---|
| 1 | futex helper arity, stop/continue order, EINTR, stack after SIGSTOP | `native-abi.md` §3.4 (rdi = word address, rsi = expected value; SIGSTOP before touching the futex; no stack use after the stop; exit on 0 or EAGAIN; EINTR and exit status unspecified, defaults given) |
| 2 | the trampoline: call or jump, alignment, return | `native-abi.md` §3.5 and §4 (rsp at the image start, `ret` pops the trampoline, loads from +8..+56, ABI-conformant entry; call vs jump implementation-defined; process terminates after return, status unspecified) |
| 3 | server behaviour on EOF or error | `wire-protocol.md` §10 (plain server stops and returns, exit status unspecified; persistent server accepts again; no SIGPIPE death); executables in `bootstrap-handshakes.md` §6 |
| 4 | reading requests | `wire-protocol.md` §3 (exactly 56 bytes, short reads accumulated, no read-ahead or peek, response before the next read) |
| 5 | architecture and byte order | `native-abi.md` §1 (x86-64 LP64 little-endian only; describe structs in that layout; two's complement) |
| 6 | padding | `bootstrap-handshakes.md` §0 and `abi-layouts.generated.md` (sizes 56/64/80; padding should be zero and is ignored) |
| 7 | `futex_memfd` | `bootstrap-handshakes.md` §3 (stdin: unspecified, default -1) and §4 (stub: the third received fd) |
| 8 | stub environment variable, stripping, long paths | `bootstrap-handshakes.md` §4 (`RSYSCALL_UNIX_STUB_SOCK_PATH`; envp verbatim, stripping unspecified; paths up to 107 bytes, longer unspecified with the `/proc/self/fd` default) |
| 9 | ssh details | `bootstrap-handshakes.md` §2 (`<cwd>/data` listening before `done`, exit 0 after hand-off, two connections in order, listening fd kept open; second socket name and hand-off implementation-defined; accept order an environmental assumption) |
| 10 | array counts and string contents | `bootstrap-handshakes.md` §0 (counts from struct fields, u64 length + bytes without NUL, `=` in every env entry) |
| 11 | error range | `wire-protocol.md` §4 (raw kernel values pass through; classification is client-side; nothing native) |
| 12 | fd passing | `bootstrap-handshakes.md` §0 (1 unspecified byte plus one unpadded SCM_RIGHTS cmsg; receiver buffer of `CMSG_SPACE(4n)`; syscall fd stays blocking; CLOEXEC unspecified, default `MSG_CMSG_CLOEXEC`) |
| 13 | persistent handshake | `bootstrap-handshakes.md` §5 (4-byte count, one recvmsg, exactly `count` int32 replies; fd[0] becomes infd/outfd, fd[1] stays open; old fd shutdown or close unspecified, client GC closes; count mismatch unspecified; never unlink the path) |
| 14 | stdio in bootstrapped processes | `bootstrap-handshakes.md` §2, §3, §4 (fds 0/1/2 untouched; for the stdin bootstrap fd 0 is the handshake socket at EOF and stays fd 0) |
| 15 | stack size | `native-abi.md` §4 and §9 (4096-byte allocation, 64-byte image on top, at most 4032 and at least 4017 usable bytes, no guard page, no TLS; stay under 2 KiB) |
