# rsyscall-ng v0: native ABI (normative)

Status: v0, normative. This document specifies the C-ABI library that the client loads through
the cffi extension module `rsyscall._raw`: its build contract, the five symbols the client uses,
the stack image and `clone` arguments with which the client starts native code in a new process,
and the constraints under which that code runs. Terms are defined in `README.md` §3; layouts come
from `abi-layouts.generated.md`; byte images from `vectors/v0.json`.

## 1. Platform

v0 is x86-64 LP64 little-endian only. The stack image names the x86-64 argument registers
(`rdi`, `rsi`, `rdx`, `rcx`, `r8`, `r9`) and is written with the client's native `ffi`
(`python/ffibuilder.py:1241-1249`, `python/rsyscall/loader.py:59-79`); the `clone` stack must be
16-byte aligned "so says Intel" (`python/rsyscall/handle/process.py:265-266`). A conforming
implementation MUST target x86-64 Linux with 8-byte `long`, `size_t` and pointers and 4-byte
`int`/`pid_t`, as tabulated in `abi-layouts.generated.md` § "Scalar sizes"
(`python/ffibuilder.py:1251-1288`).

Describe structs written by a helper executable (`bootstrap-handshakes.md`) are parsed by the
client with its own `ffi`, i.e. with the layout of the client's host
(`python/rsyscall/epoller.py:744-757`, `python/rsyscall/tasks/ssh.py:265`,
`python/rsyscall/tasks/stdin_bootstrap.py:98`, `python/rsyscall/tasks/stub.py:139`), so a
helper executable MUST produce the x86-64 layouts of `abi-layouts.generated.md` even when it runs
on another host (`python/rsyscall/tasks/ssh.py:263-267`). All integers on the wire and in memory
images are two's complement (`python/rsyscall/tasks/connection.py:35-38`,
`python/rsyscall/near/sysif.py:206-210`).

## 2. Build contract

The extension module `rsyscall._raw` is built by `python/ffibuilder.py` through
`setuptools` (`python/setup.py:16`, `python/pyproject.toml:1-3`) with
`set_source_pkgconfig("rsyscall._raw", ["rsyscall"], <preamble>)` (`python/ffibuilder.py:7-8`).
The native side MUST therefore install a pkg-config module named `rsyscall` whose `Cflags` let
`#include <rsyscall.h>` resolve and whose `Libs` link a library that defines the five symbols of §3
(`python/ffibuilder.py:7-8`, `python/ffibuilder.py:26`, `python/ffibuilder.py:137`,
`python/ffibuilder.py:1235-1239`). (Source for the semantics of `set_source_pkgconfig`: the cffi
documentation via Context7, `cdef.rst`: it calls `pkg-config` for the listed packages and merges
the flags into `set_source`.)

The preamble includes `<rsyscall.h>` after the system headers of `python/ffibuilder.py:9-25`,
among them `<linux/futex.h>` (`python/ffibuilder.py:15`), and before its own definitions. The
preamble itself defines `struct linux_dirent64` (`python/ffibuilder.py:52-58`), `struct kernel_sigset`
and `struct kernel_sigaction` (`python/ffibuilder.py:75-83`), `struct fdpair`
(`python/ffibuilder.py:84-87`) and `struct futex_node` (`python/ffibuilder.py:88-91`), the latter
built on `struct robust_list` from `<linux/futex.h>`. `<rsyscall.h>` MUST NOT define any of
`linux_dirent64`, `kernel_sigset`, `kernel_sigaction`, `fdpair`, `futex_node`, `robust_list` or
`robust_list_head`, and MUST compile in one translation unit after those system headers
(`python/ffibuilder.py:9-26`, `python/ffibuilder.py:52-91`).

`<rsyscall.h>` MUST define the six structs `rsyscall_trampoline_stack`, `rsyscall_syscall`,
`rsyscall_symbol_table`, `rsyscall_bootstrap`, `rsyscall_stdin_bootstrap` and `rsyscall_unix_stub`
field for field, with the same field names, types and order as the cdef
(`python/ffibuilder.py:1241-1288`), because the cdef declares them completely (no `...;`) and cffi's
API mode checks complete declarations against the C compiler's view of the real definitions
(source: cffi documentation via Context7, `cdef.rst` "Letting the C compiler fill the gaps"). The
resulting layouts are those of `abi-layouts.generated.md`.

`<rsyscall.h>` MUST declare `long rsyscall_raw_syscall(long arg1, long arg2, long arg3, long arg4, long arg5, long arg6, long sys)`
as a function (`python/ffibuilder.py:137`) and MUST make the identifiers `rsyscall_server`,
`rsyscall_persistent_server`, `rsyscall_futex_helper` and `rsyscall_trampoline` usable as C
expressions convertible to the pointer types the cdef declares
(`python/ffibuilder.py:1235-1239`):

```c
int (*const rsyscall_persistent_server)(int infd, int outfd, const int listensock);
int (*const rsyscall_server)(const int infd, const int outfd);
void (*const rsyscall_futex_helper)(void *futex_addr);
void (*const rsyscall_trampoline)(void);
```

Rationale: the cdef declares these four as `const` function-pointer variables because Python only
takes their addresses ("we need these as function pointers, we aren't calling them from Python",
`python/ffibuilder.py:1235`). In out-of-line API mode cffi generates C code that evaluates the
identifier (fetching globals on demand) and converts it to the declared pointer type, copying the
`const` qualifier into that code (source: cffi documentation via Context7, `cdef.rst` "Type
Qualifiers" and `whatsnew.rst` v1.2.0). An ordinary function prototype `int rsyscall_server(const int infd, const int outfd);`
satisfies this, since a function designator converts to a function pointer. Checked with a
self-written cffi module unrelated to rsyscall: a cdef `void (*const f3)(void);` bound to a plain C
definition `void f3(void) {}` imported fine and yielded a callable `<cdata 'void(*)()'>`; a real
`const` pointer variable worked equally. An implementation MAY therefore export ordinary functions
under these names (`python/ffibuilder.py:1236-1239`).

The client also relies on cffi being able to take the address of each of the four pointers and on
those addresses being absolute code addresses in the running process
(`python/rsyscall/loader.py:122-127`, `python/rsyscall/tasks/local.py:109`); see §8.

## 3. The five symbols

### 3.1 `rsyscall_raw_syscall`

`long rsyscall_raw_syscall(long arg1, long arg2, long arg3, long arg4, long arg5, long arg6, long sys)`
is the only function the client calls (`python/rsyscall/tasks/local.py:36-38`). It MUST use the
x86-64 System V C calling convention, MUST take the syscall number as its seventh (last)
parameter and `arg1..arg6` as the six kernel arguments in order, and MUST return the raw kernel
return value (`rax` after `syscall`) without touching `errno` or translating errors, because the
result is fed directly to the client's classifier (`python/rsyscall/tasks/local.py:38`,
`python/rsyscall/tasks/local.py:55-60`, `python/rsyscall/near/sysif.py:206-210`).

The local process issues `clone` with a fresh child stack through this very function
(`python/rsyscall/tasks/local.py:36-38`, `python/rsyscall/sched.py:139-151`,
`python/rsyscall/handle/process.py:277-279`). In the child, execution resumes right after the
`syscall` instruction with `rsp` pointing at the stack image, and the child "immediately call[s]
the ret instruction" to pop the trampoline address (`python/rsyscall/sched.py:61-71`). Therefore
the instruction following `syscall` in `rsyscall_raw_syscall` MUST be `ret`, and the function
MUST NOT use the stack after the `syscall` instruction (no frame teardown, no register restore,
no stored return value): the stack-passed seventh argument and any register shuffling MUST happen
before `syscall` (`python/rsyscall/sched.py:61-71`, `python/rsyscall/tasks/local.py:36-38`).

Rationale: the kernel's x86-64 syscall convention is `rax` = number, `rdi, rsi, rdx, r10, r8, r9`
= arguments (`r10` in place of the C ABI's `rcx`); with seven C parameters the seventh arrives on
the stack. These are platform facts, not requirements derived from `python/`.

### 3.2 `rsyscall_server(int infd, int outfd)`

Declared `int (*const rsyscall_server)(const int infd, const int outfd)` (`python/ffibuilder.py:1237`).
It MUST implement the server loop of `wire-protocol.md` §3 on `infd`/`outfd`, and MUST return
when the connection ends as specified in `wire-protocol.md` §10 (`python/rsyscall/tasks/connection.py:110-117`,
`python/rsyscall/near/sysif.py:166-178`). Its return value is Unspecified in v0 (Recommended
default: 0 on EOF, non-zero on a read or write error). It is entered through the trampoline in a
freshly cloned process with `rdi = rsi = ` the remote-side socket
(`python/rsyscall/thread.py:276-278`, `python/rsyscall/tasks/clone.py:105-107`), so it MUST
respect the constraints of §9 (`python/rsyscall/tasks/local.py:121-128`).

### 3.3 `rsyscall_persistent_server(int infd, int outfd, int listensock)`

Declared `int (*const rsyscall_persistent_server)(int infd, int outfd, const int listensock)`
(`python/ffibuilder.py:1236`) and entered through the trampoline with `[sock, sock, listening_sock]`
(`python/rsyscall/tasks/persistent.py:289-292`). It MUST serve `wire-protocol.md` §3 on the
current connection and, when the connection ends, MUST NOT return or exit but MUST accept the next
connection on `listensock` and run the reconnection handshake of `bootstrap-handshakes.md` §5
before serving again (`python/rsyscall/tasks/persistent.py:140-148`,
`python/rsyscall/tasks/persistent.py:377-405`). What it does if `accept` on `listensock` fails
is Unspecified in v0 (Recommended default: terminate the process with a non-zero status).

### 3.4 `rsyscall_futex_helper`

Declared `void (*const rsyscall_futex_helper)(void *futex_addr)` (`python/ffibuilder.py:1238`),
but Python never calls it; it only places its address in a stack image
(`python/ffibuilder.py:1235`, `python/rsyscall/tasks/clone.py:57-60`). The register contract at
entry is therefore fixed by the trampoline arguments, not by the cdef arity: `rdi` = the address of
the 32-bit futex word (`futex_pointer.near + offsetof(struct futex_node, futex)`) and `rsi` = the
value the word is expected to hold, which the client sets to 1 (`python/rsyscall/tasks/clone.py:57-60`,
`python/rsyscall/tasks/clone.py:116`, `python/rsyscall/loader.py:62-77`). The helper MUST read
both registers and MUST ignore the one-parameter prototype (`python/rsyscall/tasks/clone.py:57-60`).

The helper is cloned with `CLONE_VM|CLONE_FILES|SIGCHLD` (plus `CLONE_PARENT` when the monitor
requires it) on its own 4096-byte stack, without `ctid` (`python/rsyscall/tasks/clone.py:61-63`,
`python/rsyscall/monitor.py:300-302`). The client then waits for it to stop or exit, treats an
exit as an error ("process internal futex-waiting task died unexpectedly") and, on a stop, sends
`SIGCONT` and considers the stack reusable ("which indicates the trampoline is done and we can
deallocate the stack") (`python/rsyscall/tasks/clone.py:64-70`). Hence the helper MUST, in this
order (`python/rsyscall/tasks/clone.py:42-46`, `python/rsyscall/tasks/clone.py:64-70`):

1. consume its arguments from `rdi` and `rsi` (`python/rsyscall/tasks/clone.py:57-60`);
2. stop itself with `SIGSTOP` before touching the futex word, and MUST NOT exit before stopping
   (`python/rsyscall/tasks/clone.py:66-68`); `SIGSTOP` is required because it cannot be blocked
   and the helper inherits the parent's signal mask, in which the client keeps `SIGCHLD` blocked
   (`python/rsyscall/monitor.py:254`, `python/rsyscall/tasks/clone.py:155`);
3. MUST NOT read or write its stack after stopping, since the client may free it once it has seen
   the stop (`python/rsyscall/tasks/clone.py:64-65`, `python/rsyscall/tasks/clone.py:71`);
4. after `SIGCONT`, call `futex(addr, FUTEX_WAIT, expected, NULL)` (`python/rsyscall/tasks/clone.py:42-46`,
   `python/rsyscall/tasks/clone.py:70`);
5. terminate when the wait returns 0 (woken by the kernel's `CLONE_CHILD_CLEARTID` wake, §6) or
   fails with `EAGAIN` (the word no longer holds `expected`), because the client waits for its
   exit as the signal that the monitored process is gone (`python/rsyscall/tasks/clone.py:44-46`,
   `python/rsyscall/tasks/clone.py:129-136`).

Handling of `EINTR` and of a wake-up after which the word still holds `expected` is Unspecified
in v0 (Recommended default: re-read the word and wait again while it still equals `expected`;
this is compatible with step 5 because the kernel clears the word before waking). The exit status
is Unspecified in v0 (Recommended default: 0). The helper MUST NOT modify shared memory other
than its own stack and MUST NOT close or otherwise disturb file descriptors, since it shares the
address space and the fd table with the process it monitors (`python/rsyscall/tasks/clone.py:63`).

Rationale: Observed (black-box): the pre-existing `hello.strace` (command in `wire-protocol.md`
§8) shows the oracle helper doing `tkill(<own pid>, SIGSTOP)`, receiving `SIGCONT` from the
client (`kill(pid, SIGCONT)`), then `futex(0x7f6480e01218, FUTEX_WAIT, 1, NULL) = 0` when the
monitored process exec'd, then `exit(0)`.

### 3.5 `rsyscall_trampoline`

Declared `void (*const rsyscall_trampoline)(void)` (`python/ffibuilder.py:1239`); its address is
the first word of every stack image (`python/rsyscall/sched.py:81-82`,
`python/rsyscall/loader.py:135-137`). Entry state: the new process starts at the instruction after
`syscall` in the parent's raw-syscall primitive with `rsp` = `child_stack` = the start of the
image, 16-byte aligned (`python/rsyscall/handle/process.py:265-266`,
`python/rsyscall/handle/process.py:277`); that primitive executes `ret`, which pops the trampoline
address (`python/rsyscall/sched.py:61-71`). The trampoline therefore begins with `rsp` = image + 8,
pointing at the `rdi` slot of `struct rsyscall_trampoline_stack` (`python/rsyscall/sched.py:82`,
`python/ffibuilder.py:1241-1249`).

The trampoline MUST load `rdi, rsi, rdx, rcx, r8, r9` from image offsets +8, +16, +24, +32, +40,
+48 and the target address from +56, in that layout (`python/rsyscall/loader.py:70-78`,
`python/ffibuilder.py:1241-1249`, `python/rsyscall/sched.py:81-82`), and MUST enter the target as
a C function with those registers as its first six arguments and an ABI-conformant stack (at the
target's first instruction `rsp + 8` is a multiple of 16, as after a `call`), because the targets
are C functions (`python/ffibuilder.py:1236-1238`, `python/rsyscall/handle/process.py:265-266`).
Whether it uses `call` or `push`+`jmp` is implementation-defined. Given the alignment of the image
start, popping all seven words leaves `rsp` = image + 64, 16-byte aligned, so a `call` from there
is conformant (`python/rsyscall/handle/process.py:265-266`).

When the target returns, the process MUST terminate: there is no frame to return to, the client
expects the process to end only through `exit`/`exec` requests or the end of its server loop
(`python/rsyscall/sched.py:61-71`, `python/rsyscall/tasks/clone.py:87-98`). The exit status is
Unspecified in v0 (Recommended default: `exit_group(ret & 0xff)` where `ret` is the target's
`int` return value; a `void` target counts as 0). The trampoline MUST NOT depend on TLS, `errno`,
or any libc state (§9; `python/rsyscall/tasks/local.py:121-128`).

Rationale: Observed (black-box): in the run of `probe_persistent3.py` quoted in `wire-protocol.md`
§10, the cloned server process ended with a plain `exit(0)` right after `rsyscall_server` saw EOF;
the pre-existing `hello.strace` shows the cloned child's first syscall being `read(14, ..., 56)`,
i.e. the trampoline itself makes no syscalls before entering the target.

## 4. The stack image

The client builds the image as the 8-byte address of `rsyscall_trampoline` followed by the 56-byte
`struct rsyscall_trampoline_stack` (`python/rsyscall/sched.py:57`, `python/rsyscall/sched.py:81-82`,
`python/rsyscall/loader.py:59-79`); total 64 bytes (`abi-layouts.generated.md` § "Derived constants").

| offset | size | field | value | source |
|---|---|---|---|---|
| 0 | 8 | trampoline | address of `rsyscall_trampoline` | `python/rsyscall/sched.py:82`, `python/rsyscall/loader.py:137` |
| 8 | 8 | `rdi` | argument 1 or 0 | `python/rsyscall/loader.py:72` |
| 16 | 8 | `rsi` | argument 2 or 0 | `python/rsyscall/loader.py:73` |
| 24 | 8 | `rdx` | argument 3 or 0 | `python/rsyscall/loader.py:74` |
| 32 | 8 | `rcx` | argument 4 or 0 | `python/rsyscall/loader.py:75` |
| 40 | 8 | `r8` | argument 5 or 0 | `python/rsyscall/loader.py:76` |
| 48 | 8 | `r9` | argument 6 or 0 | `python/rsyscall/loader.py:77` |
| 56 | 8 | `function` | address of the target function | `python/rsyscall/loader.py:71` |

Argument encoding: a `FileDescriptor` becomes its fd number, a `Pointer` its absolute address, an
`int` its value; unused slots are 0; at most six arguments are allowed
(`python/rsyscall/loader.py:44-46`, `python/rsyscall/loader.py:62-69`). Native code MUST treat
every slot as a 64-bit two's-complement value (`python/ffibuilder.py:1242-1247`).

Placement: the image is written at the end of a 4096-byte allocation with 16-byte alignment, so up
to 15 unwritten bytes MAY lie above the image and the allocation extends 4096 - 64 - slack bytes
below it (`python/rsyscall/tasks/clone.py:114-115`, `python/rsyscall/tasks/clone.py:61-62`,
`python/rsyscall/handle/pointer.py:228-254`). The client checks that the allocation ends exactly
where the image starts and that the image address is a multiple of 16
(`python/rsyscall/handle/process.py:265-271`). Trampoline-entered code MUST fit its stack usage
into the bytes below the image: at most 4032 bytes are usable and at least 4017 are guaranteed,
with no guard page (`python/rsyscall/tasks/clone.py:114`, `python/rsyscall/handle/pointer.py:236-237`,
`python/rsyscall/memory/ram.py:132`). Implementations SHOULD stay well under 2 KiB of peak stack
usage (`python/rsyscall/tasks/clone.py:114`).

Byte image for `rsyscall_server(7, 7)` with the trampoline at `0x7f0000002000` and the server at
`0x7f0000001000` (vectors `stack_image`, `trampoline_stack`):

```
00 20 00 00 00 7f 00 00   +0   rsyscall_trampoline
07 00 00 00 00 00 00 00   +8   rdi = 7 (infd)
07 00 00 00 00 00 00 00   +16  rsi = 7 (outfd)
00 00 00 00 00 00 00 00   +24  rdx
00 00 00 00 00 00 00 00   +32  rcx
00 00 00 00 00 00 00 00   +40  r8
00 00 00 00 00 00 00 00   +48  r9
00 10 00 00 00 7f 00 00   +56  function = rsyscall_server
```

## 5. `clone(2)` as issued by the client

The client issues the raw `clone` syscall with the argument order `(flags, child_stack, ptid, ctid, newtls)`,
passing 0 for any pointer it does not supply (`python/rsyscall/sched.py:139-151`). Native code
MUST be prepared to be started by exactly this call (`python/rsyscall/sched.py:151`,
`python/rsyscall/handle/process.py:277-279`):

| argument | value | source |
|---|---|---|
| `flags` | caller flags `|` `CLONE_VM` `|` `CLONE_CHILD_CLEARTID` `|` `SIGCHLD`, plus `CLONE_PARENT` when the cloning task is not the monitoring task | `python/rsyscall/tasks/clone.py:101-103`, `python/rsyscall/monitor.py:300-302` |
| `child_stack` | address of the stack image (§4), 16-byte aligned | `python/rsyscall/handle/process.py:265-266`, `python/rsyscall/handle/process.py:277` |
| `ptid` | 0 | `python/rsyscall/monitor.py:302`, `python/rsyscall/sched.py:145-146` |
| `ctid` | address of the `FutexNode` + `offsetof(struct futex_node, futex)` (= node + 8) | `python/rsyscall/handle/process.py:277-279`, `python/rsyscall/tasks/clone.py:120` |
| `newtls` | 0, so no TLS is set up for the child | `python/rsyscall/monitor.py:302`, `python/rsyscall/sched.py:149-150` |

`CLONE_VM` and `CLONE_CHILD_CLEARTID` are always present ("These flags are mandatory",
`python/rsyscall/tasks/clone.py:101-103`). The caller MAY add sharing flags such as `CLONE_FILES`
(the default child of `Process.clone` is unshared, a `CLONE.FILES` child shares the fd table) or
namespace flags such as `CLONE_NEWPID`/`CLONE_NEWUSER`, so the server MUST work both with a shared
and with a copied fd table (`python/rsyscall/thread.py:271-278`, `python/rsyscall/tasks/clone.py:145-148`,
`python/rsyscall/tests/test_clone.py:14`). The persistent server is cloned with
`CLONE_FILES|CLONE_FS|CLONE_SIGHAND` plus the mandatory flags (`python/rsyscall/tasks/persistent.py:291`).

The server child MUST be cloned before its futex helper, and the client relies on that order for
`unshare(NEWPID)` and `ns_last_pid` manipulation (`python/rsyscall/tasks/clone.py:117-120`,
`python/rsyscall/tasks/clone.py:128`). The helper's own `clone` uses `CLONE_VM|CLONE_FILES|SIGCHLD`
(plus `CLONE_PARENT` when required), its own 4096-byte image and no `ctid`
(`python/rsyscall/tasks/clone.py:61-63`, `python/rsyscall/monitor.py:300-302`). The exact flag
values are recorded in vector `clone_args`.

Rationale: Observed (black-box): the pre-existing `hello.strace` shows
`clone(child_stack=0x7f6480e011d0, flags=CLONE_VM|CLONE_CHILD_CLEARTID|SIGCHLD, child_tidptr=0x7f6480e01218)`
followed by `clone(child_stack=0x7f6480e021e0, flags=CLONE_VM|CLONE_FILES|SIGCHLD)`; the
`child_tidptr` is 8 past the node written by the client.

## 6. The futex EOF mechanism

Because the server process may share its fd table with others, the client cannot rely on the
remote socket being closed when the process exits or execs; instead it uses the `ctid` futex: the
kernel clears the word and wakes a waiter on exit or exec, the helper exits, and the client shuts
down the access-side socket so its pending reads see EOF (`python/rsyscall/tasks/clone.py:87-98`,
`python/rsyscall/tasks/clone.py:121-138`). The pieces native code MUST honour
(`python/rsyscall/tasks/clone.py:116`, `python/rsyscall/tasks/clone.py:128-136`):

| element | value | source |
|---|---|---|
| `FutexNode` written before `clone` | `next = NULL`, `futex = 1`, 4 bytes of zero tail padding (vector `futex_node`) | `python/rsyscall/tasks/clone.py:116`, `python/rsyscall/linux/futex.py:23-32` |
| `ctid` | address of `futex` inside the node (node + 8) | `python/rsyscall/handle/process.py:277-279` |
| kernel action | on exit or exec of the child, clear the word and `FUTEX_WAKE` one waiter | `python/rsyscall/tasks/clone.py:92-94` |
| helper | waits with `futex(addr, FUTEX_WAIT, 1)`, exits when woken (§3.4) | `python/rsyscall/tasks/clone.py:42-46` |
| client | `waitpid` on the helper, then `shutdown(SHUT_RDWR)` on the access socket | `python/rsyscall/tasks/clone.py:129-138` |

The server MUST NOT write to the futex word or wake the futex itself; the only legitimate wake
is the kernel's on exit or exec (`python/rsyscall/tasks/clone.py:92-98`). The stack image, its
allocation and the futex node are freed by the client once the process has died or exec'd
(`python/rsyscall/handle/process.py:200-215`), so native code MUST NOT use them after an `exec`
request has been issued (the process image is gone anyway) and MUST NOT expect them to survive its
own exit (`python/rsyscall/handle/process.py:200-207`). The helper's stack is currently never
freed ("TODO uh we need to actually call something to free the stack",
`python/rsyscall/tasks/clone.py:71`), but the helper MUST NOT rely on that (§3.4).

Rationale: `next = NULL` rather than a pointer back to a list head means the node is not a valid
robust list; the client notes that the kernel would `EFAULT` when walking it and therefore never
maps address 0 (`python/rsyscall/linux/futex.py:25-28`). `set_robust_list` exists in the client
but no bootstrap or clone path uses it (`python/rsyscall/linux/futex.py:58-69`).

## 7. Memory model

Rationale: all addresses exchanged with native code are absolute addresses in the process that
executes them (`python/rsyscall/loader.py:122-127`, `python/rsyscall/tasks/connection.py:35-38`).
The client allocates everything it hands to native code, stacks, futex nodes and syscall
arguments alike, from one 4 GiB `mmap(PROT_READ|PROT_WRITE, MAP_SHARED|MAP_ANONYMOUS)` arena per
bootstrapped or local process (`python/rsyscall/memory/allocator.py:293-298`,
`python/rsyscall/memory/allocator.py:332-334`, `python/rsyscall/sys/mman.py:87-93`), inherited by
clones (`python/rsyscall/tasks/clone.py:166`); allocations use alignment 1 and no guard pages
(`python/rsyscall/memory/ram.py:132`), and freed pages are returned with `MADV_REMOVE`
(`python/rsyscall/memory/allocator.py:171-205`), so memory freed by the client may read as zero or
be repurposed at any later time. An additional 8 KiB `MAP_SHARED` mapping is created per clone but
never used (`python/rsyscall/tasks/clone.py:108-111`).

## 8. `struct rsyscall_symbol_table`

The table holds four `void *` in the order `rsyscall_server`, `rsyscall_persistent_server`,
`rsyscall_futex_helper`, `rsyscall_trampoline` (`python/ffibuilder.py:1255-1260`;
`abi-layouts.generated.md`). It is the first member of every describe struct
(`python/ffibuilder.py:1262`, `python/ffibuilder.py:1270`, `python/ffibuilder.py:1279`). The client
converts each pointer to an integer and treats it as the address of that function in the
described process, later placing it in stack images for clones of that process
(`python/rsyscall/loader.py:114-133`, `python/rsyscall/tasks/ssh.py:303`,
`python/rsyscall/tasks/stdin_bootstrap.py:131`, `python/rsyscall/tasks/stub.py:174`). A helper
executable MUST fill the table with the absolute run-time addresses, in its own address space, of
the same four entry points specified in §3, and those addresses MUST stay valid for the lifetime
of the process and of every process cloned from it (`python/rsyscall/loader.py:122-127`,
`python/rsyscall/thread.py:276-278`). `rsyscall_raw_syscall` is not part of the table; the client
only calls it in its own process through `lib` (`python/rsyscall/tasks/local.py:38`,
`python/rsyscall/tasks/local.py:109`).

## 9. Freestanding constraints

Code reached through the trampoline (the servers, the helper and anything they call) runs in a
process created by `clone` without `CLONE_SETTLS`, so its TLS pointer, if any, is the parent
thread's; the client removes the readline `SIGWINCH` handler precisely because children run in an
environment "lacking TLS for one" (`python/rsyscall/tasks/local.py:121-128`,
`python/rsyscall/sched.py:149-150`). Trampoline-entered code MUST NOT use thread-local storage,
`errno`, or any libc or language-runtime state that assumes an initialised thread, and MUST NOT
call libc functions that do (`python/rsyscall/tasks/local.py:121-128`).

The stack budget is the client's 4096-byte allocation minus the 64-byte image and up to 15 bytes
of alignment slack, with no guard page (§4; `python/rsyscall/tasks/clone.py:114-115`,
`python/rsyscall/handle/pointer.py:236-237`). Trampoline-entered code MUST NOT exceed it and
MUST NOT assume a stack overflow would be detected (`python/rsyscall/memory/ram.py:132`).

Signal dispositions and the signal mask are inherited from the parent (the client keeps `SIGCHLD`
blocked and propagates its tracked mask to the child task, `python/rsyscall/monitor.py:254`,
`python/rsyscall/tasks/clone.py:155`); handlers installed by the parent may run in the child
(`python/rsyscall/tasks/local.py:121-128`). Native code MUST NOT change signal dispositions or the
signal mask of the process, since the client tracks and manipulates both itself
(`python/rsyscall/tasks/clone.py:155`, `python/rsyscall/signal.py:279-288`), and MUST NOT depend
on any particular disposition being inherited (`wire-protocol.md` §10 on `SIGPIPE`;
`python/rsyscall/tasks/persistent.py:16-22`).

The address space is shared with the parent (`CLONE_VM`, `python/rsyscall/tasks/clone.py:101-103`),
so native code MUST NOT write outside its own stack, the memory the client told it to write
(memory writes, `wire-protocol.md` §5) and the results of the syscalls it was asked to perform
(`python/rsyscall/near/sysif.py:101-111`). It MUST NOT close or modify file descriptors on its own
initiative, because the fd table may be shared and the client tracks every descriptor
(`python/rsyscall/tasks/clone.py:145-148`, `python/rsyscall/handle/fd.py:234-247`).
