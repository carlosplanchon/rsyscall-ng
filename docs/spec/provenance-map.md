# Provenance map: native-side facts encoded in `python/`

Status: **input document** for the clean-room specification in `docs/spec/`. Non-normative.

How it was produced: on 2026-09-29 an exploration agent whose read access was restricted to
`python/` (no access to `reference/`, `.venv/`, or any `.c`, `.h` or `.S` file) catalogued every
place where the MIT-licensed Python side establishes a fact about the native side: the C-ABI
library used through the cffi module `rsyscall._raw` and the helper executables the Python code
starts. Struct offsets were computed by mirroring the cdef field lists with `ctypes` on x86-64
(pure computation; no header was read). Line numbers refer to the tree at the commit that adds
this file; re-verify with `grep -n` before citing. Where the map says "Python assumes" or
"Python ignores", that is a statement about the client, not about how the native side works.

"Resolved in" pointers for the open questions at the end are filled in by the specification
documents.

---

## 1. cffi cdef declarations: `python/ffibuilder.py`

**Build and linkage**
- L7-8: `ffibuilder.set_source_pkgconfig("rsyscall._raw", ["rsyscall"], """`. The extension module is `rsyscall._raw`; its cflags/libs come from a pkg-config package named `rsyscall`.
- L26: `#include <rsyscall.h>` sits inside the set_source preamble, after the system headers at L9-25 and before `sched.h` and the rest at L27-50.
- The preamble defines several things itself: `struct linux_dirent64` (L52-58), `struct kernel_sigset`/`kernel_sigaction` (L75-83), `struct fdpair` (L84-87) and `struct futex_node` (L88-91). It also adds typedefs `sighandler_t`/`sigrestore_t` (L72-73) and macros (L62-71, L93-95). `futex_node` uses `struct robust_list` from `<linux/futex.h>` (L15).
  - Consequence: `rsyscall.h` must not also define these, or the translation unit gets a redefinition error.
- No `rsyscall_*` item is defined in the preamble, so all of them must come from `rsyscall.h` and the library. They are fully declared (no `...;`), so cffi's API mode requires the real C definitions to match the cdef exactly. Only `struct cmsghdr` (L1336-1342) uses `...;`.

**Functions** (L137 and L1235-1239):
```c
long rsyscall_raw_syscall(long arg1, long arg2, long arg3, long arg4, long arg5, long arg6, long sys);
// we need these as function pointers, we aren't calling them from Python
int (*const rsyscall_persistent_server)(int infd, int outfd, const int listensock);
int (*const rsyscall_server)(const int infd, const int outfd);
void (*const rsyscall_futex_helper)(void *futex_addr);
void (*const rsyscall_trampoline)(void);
```
- Python only calls `rsyscall_raw_syscall`. The other four are only used as addresses.
- The other function declarations in the cdef are libc, not rsyscall: `memcpy` (L1234), the `epoll_*` functions (L121-123), `unlinkat`/`linkat` (L135-136).

**Structs** (x86-64 LP64 offsets):

| struct | lines | fields (type @offset) | sizeof |
|---|---|---|---|
| `rsyscall_trampoline_stack` | 1241-1249 | `int64_t rdi@0, rsi@8, rdx@16, rcx@24, r8@32, r9@40; void* function@48` | 56 |
| `rsyscall_syscall` | 1251-1254 | `int64_t sys@0; int64_t args[6]@8` | 56 |
| `rsyscall_symbol_table` | 1255-1260 | `void* rsyscall_server@0, rsyscall_persistent_server@8, rsyscall_futex_helper@16, rsyscall_trampoline@24` | 32 |
| `rsyscall_bootstrap` | 1261-1268 | `symbols@0; pid_t pid@32; int listening_sock@36, syscall_sock@40, data_sock@44; size_t envp_count@48` | 56 |
| `rsyscall_stdin_bootstrap` | 1269-1277 | `symbols@0; pid_t pid@32; int syscall_fd@36, data_fd@40, futex_memfd@44, connecting_fd@48; [4-byte pad @52]; size_t envp_count@56` | 64 |
| `rsyscall_unix_stub` | 1278-1288 | `symbols@0; pid_t pid@32; int syscall_fd@36, data_fd@40, futex_memfd@44, connecting_fd@48; [pad @52]; size_t argc@56, envp_count@64; uint64_t sigmask@72` | 80 |
| `futex_node` | 88-91 (preamble), 1347-1352 (cdef) | `struct robust_list list@0; uint32_t futex@8; [4-byte tail pad]` | 16 |
| `robust_list` / `robust_list_head` | 1354-1356 / 1358-1362 | `next@0` / `list@0; unsigned long futex_offset@8; list_op_pending@16` | 8 / 24 |
| `fdpair` | 84-87, 108-112 | `int first@0, second@4` | 8 |

- Comments at L1344 and L1347-1348: `//// ugh, have to take this over to get notification of thread exec` and `// this is our custom robust_list + futex structure`.
- `fdpair` is only the kernel `int[2]` for pipe/socketpair (`rsyscall/sys/socket.py` L237-262, `rsyscall/unistd/pipe.py` L31-47). It is not a native-library contract.
- `robust_list_head` and `set_robust_list` are defined (`rsyscall/linux/futex.py` L38-69) but no bootstrap or clone path uses them.
- Other cdef items that appear in the protocol: `SCM_RIGHTS` (L1297), `iovec` (L1317-1320), `msghdr` (L1323-1334).

---

## 2. Syscall wire protocol

### `python/rsyscall/tasks/connection.py`

**Framing**
- L3-5 docstring: "Write a syscall request out as a fixed-size struct containing a syscall number and the arguments, read the syscall response in as a 64-bit long."
- Request (L32-50): `ffi.new('struct rsyscall_syscall const*', {"sys": ..., "args": (arg1..arg6)})`: 56 bytes in native layout and byte order.
- Response (L64-80): `ffi.cast('long*', ...)`, i.e. 8 bytes, signed.
- There is no header, length field or request id. Responses are matched to requests strictly in FIFO order through `response_queue`.

**Sending (`_run_requests`, L193-226)**
- The loop takes one request at a time.
- Syscalls: `await self.fd.send_all_bytes(syscall, MSG.NOSIGNAL)`, then the syscall is appended to `response_queue` (L200, L207).
- `Write` requests send their raw bytes the same way (L211). They complete once the bytes are sent (L217-218).
- `Read` and `Barrier` requests go straight to `response_queue` (L219-224).
- A send failure raises `SyscallSendError` (L201-204, L212-215).
- `send_all` retries partial sends (`rsyscall/epoller.py` L595-611), so one request may reach the server in several pieces.

**Receiving (`_run_responses`, L228-259)**
- One `AsyncReadBuffer` is shared for everything.
- A syscall slot reads `read_struct(SyscallResponse)`, 8 bytes (L236). A `Read` slot reads exactly `count` bytes (L247). A `Barrier` slot reads nothing (L254-257).
- Any read failure raises `SyscallHangup` (L237-240, L248-251).

**Memory write (L158-168)**
```python
reset(self.infallible_recv(to_span(dest)))   # -> recvfrom(server_fd, dest, len, MSG_WAITALL, 0, 0)
await self.write_to_fd(data)                 # raw bytes follow the request on the same stream
```
- The raw data is consumed by a `recvfrom` that the server executes on its own syscall fd (`rsyscall/sys/socket.py` L592-600, L679-681).
- A partial result raises "somehow got a partial recv with MSG.WAITALL, the syscall server will now be broken" (L160-161).

**Memory read (L179-188)**
```python
read_fut = Future.start(self.read_from_fd(src.size()))   # Read(count) slot queued first
await self.infallible_send(src)                           # -> sendto(server_fd, src, len, 0, 0, 0)
```
- On the server-to-client stream this gives `len` raw memory bytes, then the 8-byte `sendto` result.
- A partial send raises "somehow got a partial send..." (L181-182).
- The order is deterministic because `reset` and `Future.start` run the coroutine synchronously up to its first `shift` (`python/dneio/core.py` L108-127, `python/dneio/concur.py` L94-106); `RequestQueue.request` enqueues at that `shift` (`concur.py` L28-45).

**Other operations**
- `barrier()` (L190-191) puts nothing on the wire. It completes once every earlier response has been consumed.
- `get_activity_fd` (L101-108) returns `server_fd`: "this fd is read by the rsyscall server to receive syscalls, and when this fd is readable, it means there's syscalls to be read."
- `close_interface` (L110-117) does only `shutdown(SHUT.RDWR)` on the local end: "We don't close server_fd".
- Syscalls are shielded from trio cancellation (L135-147).
- The docstring (L7-9) claims requests are batched, but the code sends each request separately. This makes no difference on the wire.

**Where `server_fd` comes from**
- clone: `Trampoline(self.loader.server_func, [sock, sock])` (`thread.py` L276-278).
- persistent processes: `[sock, sock, listening_sock]` (`persistent.py` L292).
- ssh bootstrap: `syscall_sock` (`ssh.py` L281-286).
- stdin bootstrap: `syscall_fd` (`stdin_bootstrap.py` L115-120).
- Unix stub: `syscall_fd` (`stub.py` L157-162).
- Responses and memory-read data are read from the same local socket, so the server must read requests from, and write responses and data to, one and the same socket.

**Blocking mode and epoll**
- `python/rsyscall/network/connection.py` L149: "have to set NONBLOCK after creation because we want the other end to be blocking". So the server's end is blocking.
- Activity fd: `python/rsyscall/epoller.py` L62-70 explains it. L180-184 registers it level-triggered with `EPOLL.IN|EPOLL.RDHUP|EPOLL.PRI|EPOLL.ERR|EPOLL.HUP` ("not edge triggered"). L189-192 retries `epoll_wait` on `SyscallHangup`.

### `python/rsyscall/near/sysif.py`

**Error convention (L206-210)**
```python
if -4095 < response < 0:
    err = -response
    raise OSError(err, os.strerror(err))
```

**Guarantees in the `SyscallInterface` docstrings**
- `syscall` (L42-94): a syscall is either submitted and completed, or not submitted at all. Syscalls are cancelled via a signal and EINTR (L81-86). If the server dies or the connection hits EOF, the call raises (L88-91).
- `write` (L101-111): "the write is guaranteed to be performed before any other operations performed through this SyscallInterface". This requires the server to execute requests strictly one at a time and in order.
- `barrier` (L113-126) and the activity fd (L134-145) are documented alongside.

**Exceptions**
- `SyscallError` (L166-178) is permanent: every later call fails too.
- `SyscallHangup` (L180-194): "for some syscalls (exit and exec, namely), this result indicates success".
- `SyscallSendError` (L196-204): "We know for sure that this syscall was not sent and was not executed."

**Where the hangup-means-success rule is used**
- `rsyscall/unistd/exec.py` L8-31: `execve`, `execveat` and `exit` swallow `SyscallHangup`.
- `rsyscall/handle/__init__.py` L239-302 calls `close_interface()` afterwards.
- `rsyscall/handle/fd.py` L234-247 handles a hangup during `close`.

### `python/rsyscall/tasks/local.py`
- L36-38: `return lib.rsyscall_raw_syscall(arg1, arg2, arg3, arg4, arg5, arg6, number)`. The syscall number is the 7th and last parameter. The call is synchronous and blocks the interpreter.
- L55-60: the return value goes straight into `raise_if_error`, so the native function must return the raw kernel value (`-errno`), not libc's `-1`/`errno` convention.
- L67-76: local memory access is `ffi.memmove(ffi.cast('void*', addr), data, len)` and `bytes(ffi.buffer(ffi.cast('void*', addr), size))`. `barrier` is a no-op (L78-80).
- L109: `NativeLoader.make_from_symbols(task, lib)`.
- L121-128: the readline SIGWINCH handler is reset because children would segfault, "the environment being totally different (lacking TLS for one)". In other words, cloned children run without TLS.

---

## 3. Native function contracts and the loader

### `python/rsyscall/loader.py`
- `Trampoline` (L38-57): a function pointer plus at most 6 arguments (L44-46). Each argument is a `FileDescriptor` (its fd number), a `Pointer` (its address), or an int.
- `TrampolineSerializer` (L59-79): arguments map in order to `rdi, rsi, rdx, rcx, r8, r9`; unused slots are 0; `'function': ffi.cast('void*', int(val.function.near))`.
- `make_from_symbols` (L114-133) reads `symbols.rsyscall_server`, `.rsyscall_persistent_server`, `.rsyscall_trampoline` and `.rsyscall_futex_helper` by attribute. `symbols` is either `rsyscall._raw.lib` or a `struct rsyscall_symbol_table` cdata (docstring L116-121). L123: `int(ffi.cast('ssize_t', cffi_ptr))`, so the values must be absolute runtime addresses in the target process. L126 builds a fake mapping around each address.
- `make_trampoline_stack` (L135-137): `Stack(self.trampoline_func, trampoline, TrampolineSerializer())`.

### Stack layout: `python/rsyscall/sched.py`
- L61-71: "All rsyscall.threades, after executing the clone syscall, immediately call the "ret" instruction. Thus, the first value on any stack passed to clone must be a function pointer, which ret will pop off and begin executing." This applies to `rsyscall_raw_syscall` too, because the local process runs `clone` through it.
- L57 and L81-82: `_address = struct.Struct("Q")`; `to_bytes = pack(function) + serializer.to_bytes(data)`.
- The resulting 64-byte image at `child_stack` is: `+0` address of `rsyscall_trampoline`, `+8..+47` `rdi..r9`, `+56` the real target function.
- L139-151: raw `SYS.clone` argument order is `(flags, child_stack, ptid, ctid, newtls)`, with 0 for any argument not given.

### Placement and alignment
- `python/rsyscall/handle/pointer.py` L228-254 (`split_from_end`, `write_to_end`): the 64 bytes go at the top of the buffer; up to 15 unwritten bytes may remain above them.
- `python/rsyscall/handle/process.py` L265-271 enforces `child stack must have 16-byte alignment, so says Intel`, and that the stack allocation ends exactly where the data starts. L277-279 passes `ctid` as `ctid_n + ffi.offsetof('struct futex_node', 'futex')`, i.e. node address + 8. L200-215 frees the stack and ctid memory once the child dies or execs.
- `python/rsyscall/monitor.py` L300-302: `flags |= CLONE.PARENT` when needed, then `clone(flags|SIG.CHLD, child_stack, None, ctid, None)`.
- Stack size is `malloc(Stack, 4096)` (`clone.py` L61, L114) from an allocator that uses `alignment=1` (`memory/ram.py` L132): about 4 KiB of stack, no guard page set up by Python.

### `python/rsyscall/tasks/clone.py`: `clone_child_task` (L74-167)
- L101-103: `flags |= CLONE.VM|CLONE.CHILD_CLEARTID`; the comment calls these mandatory because without CLONE_VM, CHILD_CLEARTID does not work properly.
- L105: one channel from `connection.open_async_channels(1)`. L107: `trampoline_func(remote_sock)`.
- L116: `futex_pointer = await task.ptr(FutexNode(None, Int32(1)))`: the futex word starts at 1 and its `next` pointer is NULL.
- L117-120: the main child must be cloned before the futex helper ("relevant in ... unshare(NEWPID) and manipulation of ns_last_pid").
- L87-98 and L121-138 describe the EOF mechanism: the kernel clears the ctid futex on exit or exec; the futex helper then exits; Python responds with `access_sock.handle.shutdown(SHUT.RDWR)`, so pending reads see EOF.
- L108-111: an 8 KiB `MAP.SHARED` arena is created but never used (TODO comment).
- L157-165: ownership of `remote_sock` moves to the child; the child gets `SyscallConnection(access_sock, remote_sock_handle)`.

### `launch_futex_monitor` (`clone.py` L39-72)
- Arguments (L57-60): `[int(futex_pointer.near + ffi.offsetof('struct futex_node','futex')), futex_pointer.value.futex]`, so `rdi` is the address of the futex word and `rsi` is the expected value (1). The cdef declares only one parameter (see open questions).
- L42-46 describe what the helper does: "calls futex(futex_pointer, FUTEX_WAIT, futex_pointer.value) and then exits".
- L61-63: stack is 4096 bytes aligned to 16. Flags are `CLONE.VM|CLONE.FILES` (plus `SIGCHLD`, and `CLONE_PARENT` when needed). No ctid is set.
- L64-70, the SIGSTOP/SIGCONT dance:
  ```python
  # wait for futex helper to SIGSTOP itself,
  # which indicates the trampoline is done and we can deallocate the stack.
  state = await futex_pid.waitpid(W.EXITED|W.STOPPED)
  if state.state(W.EXITED): raise Exception("process internal futex-waiting task died unexpectedly", state)
  await futex_pid.kill(SIG.CONT)
  ```
- L71: `# TODO uh we need to actually call something to free the stack`.

### `python/rsyscall/linux/futex.py`
- `FutexNode` (L13-36): the list end is NULL rather than a pointer back to the head (L25-28: "the kernel will EFAULT when it hits the end").
- `RobustListHead` (L38-52): `futex_offset = offsetof(futex_node, futex)`.

---

## 4. Bootstrap handshakes

### 4.0 Stream helpers: `python/rsyscall/epoller.py`
- `_read` (L719-732) reads at most 4096 bytes per call and raises `EOFError` on EOF. Any fragmentation of the incoming stream is fine.
- `read_length` (L734-742) returns exactly N bytes.
- `read_cffi(name)` (L744-757) reads `ffi.sizeof(name)` bytes and memmoves them into a new cdata: native layout, padding included.
- `read_length_prefixed_string` (L769-776): "prefixed with a 64-bit native-byte-order size". It reads a `size_t`, then exactly that many bytes, with no terminator stripped. Bug: its `except EOFError` block does not re-raise.
- `read_length_prefixed_array(length)` (L778-783): the element count is a parameter, not read from the stream, despite the docstring saying "prefixed with its size".
- `read_envp` (L785-801): `key, val = elem.split(b"=", 1)`, then `os.fsdecode`. An element without `=` raises.
- `read_line` (L821-826): splits on `b"\n"` and strips it. There is no `\r` handling.

### 4.1 ssh: `python/rsyscall/tasks/ssh.py` and `python/rsyscall/tasks/ssh_bootstrap.sh`

**Executable and local socket**
- L105: the executable is `<librsyscall>/libexec/rsyscall/rsyscall-bootstrap`.
- L157-161: it is opened `O.RDONLY`. The local socket path is `$TMPDIR/<last ssh arg><8 random [A-Z0-9]>.sock`.

**Stage 1: `make_bootstrap_dir` (L165-208)**
- The ssh process's stdin is the bootstrap executable file (L187) and its stdout is a pipe (L186). The remote command is the full script text (L188):
  ```sh
  dir="$(mktemp --directory)"
  cat >"$dir/bootstrap"
  chmod +x "$dir/bootstrap"
  cd "$dir" || exit 1
  echo "$dir"
  exec "$dir/bootstrap" socket
  ```
  So only that single file is copied to the remote host.
- Python reads line 1 as the temp dir (L201). Line 2 must be exactly `done` (L202-204). A sentinel is needed because "openssh doesn't close its local stdout when it sees HUP/EOF" (L197-199).
- L171-180 docstring: "listens on two sockets in this temporary directory. One of them, we'll ssh forward back... The other, the main bootstrap process will connect to, to grab the listening socket fd".
- L208: `await child_pid.check()`, which waits for the socket-mode process to exit and raises unless the exit code is 0 (`monitor.py` L194-207).

**Stage 2: `ssh_forward` (L210-230, L247-248)**
- Runs `ssh ... -L ./<name>:<tmp>/data -n "echo forwarded; exec sleep 60"` and expects the line `forwarded`. So the socket-mode bootstrap must be listening at `<tmp>/data`.

**Stage 3 (L250-253)**
- Runs `ssh ... -n "cd <tmp>; exec ./bootstrap rsyscall"`.

**Connections (L256-262)**
- The comment says "Connect to local socket 4 times", but the code makes only 2 connections: `AF_UNIX, SOCK_STREAM|NONBLOCK` to the forwarded path. The first connection is the syscall socket, the second is the data socket.

**Describe (L263-267)**
- Python reads `struct rsyscall_bootstrap`, then `envp_count` length-prefixed strings. Nothing else is read from the data socket.

**How the fields are used**
- `syscall_sock` becomes `server_fd` (L281-286). `data_sock` is only wrapped in a handle (L287).
- For `listening_sock`, Python sets `O_NONBLOCK` itself and uses it as the remote `accept` side of `ListeningConnection` (L288, L293-299).
- `symbols` feeds the loader (L303). fds 0/1/2 are taken as stdio (L307-309).
- "we assume ssh zeroes the sigmask before starting us" (L290).
- The first remote syscalls are a 4 GiB mmap, `epoll_create`, and the SIGCHLD signalfd (L289-292).

### 4.2 stdin bootstrap: `python/rsyscall/tasks/stdin_bootstrap.py`
1. The path is `<librsyscall>/libexec/rsyscall/rsyscall-stdin-bootstrap` (L54). The test runs it as `Command(path, ['rsyscall-stdin-bootstrap'], {})` (`tests/test_stdinboot.py` L17).
2. L72-80: create a `socketpair(AF_UNIX, SOCK_STREAM)`, dup2 one end onto the child's fd 0, and exec the command.
3. L83-86: open two channels (syscall, data) and get `connection_fd` from `prep_fd_transfer()`.
4. L87-90: one `sendmsg` on the parent's end, flags 0. It carries a 1-byte iov from an uninitialized `malloc`, and one SCM_RIGHTS cmsg holding `[passed_syscall_sock, passed_data_sock, connection_fd]` in that order.
5. L91-95: Python closes its copies and `parent_sock`, so the bootstrap's stdin reaches EOF after that byte.
6. L97-99: Python reads `struct rsyscall_stdin_bootstrap`, then `envp_count` strings, from the data channel.
7. Assumptions and field use: the pid namespace is shared with the parent (L104-110), and "we assume our SignalMask is zero'd" (L122). `connecting_fd` becomes `FDPassConnection` (Python itself later calls `recvmsg` on it, `network/connection.py` L116-135). `data_fd` and `futex_memfd` are never used.

### 4.3 Unix stub: `python/rsyscall/tasks/stub.py`
- **Listening socket** (L78-84): `AF_UNIX, SOCK_STREAM|SOCK_NONBLOCK`, then `bind`, then `listen(10)`.
- **Wrapper script** (L91-99): `<librsyscall>/libexec/rsyscall/rsyscall-unix-stub`, socket at `<dir>/<name>.sock`, wrapper file mode 0o755:
  ```sh
  #!/bin/sh
  RSYSCALL_UNIX_STUB_SOCK_PATH={sock} exec {bin} "$0" "$@"
  ```
  The docstring at L7-8 names a different variable, `RSYSCALL_UNIX_STUB_SOCK`.
- **Handshake after `accept`** (L111-142):
  1. Open two channels: syscall and data (L121-122).
  2. Create a memfd with `memfd_create("child_robust_futex_list")`; `MFD_CLOEXEC` is always added (`linux/memfd.py` L35).
  3. Send one `sendmsg` with a 1-byte iov and SCM_RIGHTS holding `[syscall, data, futex_memfd, connection]` (L127-131).
  4. Invalidate the local copies (L133-136).
  5. Read, in order: `struct rsyscall_unix_stub`, then `argc` length-prefixed argv strings (argv[0] included), then `envp_count` env strings (L138-142).
  6. `accept()` returns `argv[1:]` (L113-114).
- **Signal mask** (L164): `Sigset({SIG(bit) for bit in bits(describe_struct.sigmask)})`. `bits()` is one-indexed (`struct.py` L100-105), so bit n-1 means signal n, the kernel convention (`signal.py` L127-131). `ChildPidMonitor.make` then blocks SIGCHLD; it checks that the old mask is a superset of the reported mask (`monitor.py` L99-102, `signal.py` L290-304) and raises if SIGCHLD was already in the reported mask (`signal.py` L281-283).
- **Futex memfd** (L182-183): `#### TODO set up futex I guess`. The reported `futex_memfd` number is never used.

### 4.4 Persistent server: `python/rsyscall/tasks/persistent.py`

**Creation (L269-310)**
- A blocking `AF_UNIX SOCK_STREAM` socket (CLOEXEC is added by `sys/socket.py` L618) is bound to the path, followed by `listen(1)` (L286-288).
- Clone flags are `CLONE.FILES|CLONE.FS|CLONE.SIGHAND`, plus VM, CHILD_CLEARTID and SIGCHLD.
- The trampoline calls `persistent_server_func` with `[sock, sock, listening_sock]` (L289-292).

**Making it persistent (L371-375)**: `unshare(CLONE_FILES)`, a userspace cloexec sweep, `setsid`, and `prctl(PR_SET_PDEATHSIG, 0)`. All plain syscalls; no native function is involved.

**What happens on disconnect (L141-144)**: after Python shuts down its write end, "any currently running or pending syscalls ... will be able to finish and receive their response, after which the syscall server will close its end of the current connection and start listening for a new connection."

**Reconnect (L377-405)**
1. Optionally prep the process (L381-388: "the file descriptors opened by the C code ... will leak if the process is in a shared fd table").
2. Run the fd-table GC.
3. `SHUT_WR` on the old local end (L392).
4. Open two new channels (L393).
5. Run `_connect_and_send` (L312-338): `connect(path)`; `write(Int32(2))`, 4 bytes, native `struct 'i'`; `sendmsg` with a 1-byte iov plus SCM_RIGHTS `[syscall_sock, data_sock]`; read `2 x Int32`, looping until 8 bytes are in (the server-side fd numbers, in the same order); `close`.
6. The reply's first entry becomes the new `server_fd` (L398-402). Then `set_new_conn`, then GC "the old interface fds" (L404).

**Error behaviour**
- Syscalls block while disconnected: `SyscallSendError` leads to a retry (L198-236). `read` retries on `BrokenPipeError` (L238-260). `barrier` is implemented as `getpid` (L262-266).
- The test expects `ConnectionRefusedError` after the process has exited (`tests/test_persistent.py` L41-48).

### 4.5 Is there an `rsyscall-server` executable?
- No. Nothing in `python/` starts an `rsyscall-server` executable, and nothing mentions `describefd`. Only the `rsyscall_server` symbol appears (`ffibuilder.py` L1237 and L1256, `loader.py` L129).
- The only executables referenced are `rsyscall-bootstrap`, `rsyscall-stdin-bootstrap` and `rsyscall-unix-stub`. Their paths come from a generated module, `rsyscall._nixdeps.librsyscall`, which is not in the tree.

### 4.6 Channels: `python/rsyscall/network/connection.py`
- **`FDPassConnection`** (L94-166): channels are socketpairs (L137-143); `move_fds` sends a 1-byte message with SCM_RIGHTS, and the target task receives it with `recvmsg` (L116-135); only the access side is made non-blocking (L145-153); `prep_fd_transfer` returns the target-side fd (L155-156).
- **`ListeningConnection`** (L168-221): Python connects to the access address, then calls `accept` on the remote listening fd; `prep_fd_transfer` returns the listening fd (L209-210).
- Across all bootstraps, the native side never talks on `connecting_fd` or `listening_sock`. Python drives both through syscalls, so the native side just has to leave them open.

---

## 5. Memory and allocation
- `python/rsyscall/memory/allocator.py` L293-298: `mmap(size, PROT.READ|PROT.WRITE, MAP.SHARED)`, with `MAP.ANONYMOUS` added by `sys/mman.py` L87-93. L332-334: the size is `2**32`, one mapping per bootstrapped or local process; clones inherit it (`clone.py` L166). L171-205: freed pages are returned with `MADV.REMOVE`.
- `python/rsyscall/sys/mman.py` L113-127 assumes a 4096-byte page and asserts that lengths are multiples of it.
- `python/rsyscall/memory/ram.py` L132: allocations use `alignment=1`.
- Consequence: thread stacks (4 KiB), futex nodes and syscall arguments all live in this shared anonymous mapping, and every address sent to the server is an absolute address in the target process.

---

## 6. Everything else
- **`lib` calls outside the files above**: only `lib.strlen` (`rsyscall/sys/un.py` L63), which is libc. `lib.rsyscall_raw_syscall` (`local.py` L38) is the only rsyscall function called, and `local.py` L109 passes `lib` as the symbol source. Every other `_raw` importer uses only constants.
- **Native structs referenced from `ffi`**: `connection.py` L35, L43, L50; `loader.py` L70; `ssh.py` L265; `stdin_bootstrap.py` L98; `stub.py` L139; `clone.py` L59; `handle/process.py` L278; `linux/futex.py` L24-52.
- **SCM_RIGHTS encoding** (`python/rsyscall/sys/socket.py`): L304-314 the header is a `cmsghdr` with `cmsg_len = sizeof(cmsghdr) + len(data)`, then the data; L328-329 the data is `array.array('i', fds)`; L362-368 no `CMSG_ALIGN` padding ("TODO is this correct alignment/padding??? I don't think so..."); L389-398 `msg_controllen` is the exact size of that buffer; L578 `recvmsg` always adds `MSG_CMSG_CLOEXEC`. Users: `stdin_bootstrap.py` L88, `stub.py` L129, `persistent.py` L325, `network/connection.py` L121-131.
- **Integer encodings**: `Int32` uses `struct 'i'`, native (`struct.py` L108-123). `StructList` is plain concatenation (L142-166). `Socketpair` goes through `struct fdpair` (`socket.py` L237-262).
- **CLOEXEC defaults**: `socket()` and `socketpair()` always add `SOCK_CLOEXEC` (`socket.py` L618, L624), and memfds always get `MFD_CLOEXEC`.

---

## Open questions a spec must settle

Resolved in (see also `README.md` §6):

1. `native-abi.md` §3.4 (register contract rdi/rsi, SIGSTOP before the futex, no stack use after the stop, exit on 0 or EAGAIN; EINTR and exit status unspecified with recommended defaults).
2. `native-abi.md` §3.5 and §4 (entry state, loads from +8..+56, ABI-conformant entry; call vs jump implementation-defined; process terminates after return, exit status unspecified).
3. `wire-protocol.md` §10 (plain server stops and returns, exit status unspecified; persistent server accepts again; no SIGPIPE death); executables: `bootstrap-handshakes.md` §6.
4. `wire-protocol.md` §3.
5. `native-abi.md` §1.
6. `bootstrap-handshakes.md` §0 and `abi-layouts.generated.md`.
7. `bootstrap-handshakes.md` §3 (stdin: unspecified, recommended -1) and §4 (stub: the third received fd).
8. `bootstrap-handshakes.md` §4.
9. `bootstrap-handshakes.md` §2.
10. `bootstrap-handshakes.md` §0.
11. `wire-protocol.md` §4.
12. `bootstrap-handshakes.md` §0.
13. `bootstrap-handshakes.md` §5.
14. `bootstrap-handshakes.md` §2, §3 and §4.
15. `native-abi.md` §4 and §9.

1. **Futex helper arity.** The cdef says `void (*)(void *futex_addr)`, but Python passes `rsi = expected value` too (`clone.py` L57-60). The spec also has to define the helper's stop/continue order, how it handles EINTR, EAGAIN and spurious wakeups, and whether it may touch its stack after SIGSTOP ("we can deallocate the stack", yet L71 says it isn't actually freed).
2. **The trampoline itself.** Python never says whether the trampoline calls or jumps to the target, what stack alignment the target sees on entry (only `child_stack % 16 == 0` at clone time), or what happens when the target function returns.
3. **Server behaviour on EOF or error.** For `rsyscall_server` and the bootstrap executables this is unspecified: does it exit, with what status, or return? Only the persistent server's EOF behaviour is described (`persistent.py` L141-144).
4. **Reading requests.** The server must read exactly one 56-byte request at a time, with no read-ahead, and handle requests that arrive in pieces. Python implies this (raw write data follows inline, and the activity-fd rule) but never states it.
5. **Architecture and byte order.** Everything is native x86-64 LP64: little-endian, 8-byte `long`/`size_t`/pointers, register names in the trampoline struct. Python parses remote describe structs with the local `ffi`, so a remote host with a different ABI is silently unsupported.
6. **Padding.** There are 4 pad bytes at offset 52 in the stdin and stub structs and 4 tail pad bytes in `futex_node`. Python ignores their contents. The spec should fix the sizes: 56 (`rsyscall_bootstrap`), 64 (`rsyscall_stdin_bootstrap`) and 80 (`rsyscall_unix_stub`).
7. **`futex_memfd` in the stdin struct.** Python sends only 3 fds, so what value should this field hold? For the stub, the value is received but unused.
8. **Stub environment variable.** The code uses `RSYSCALL_UNIX_STUB_SOCK_PATH`; the docstring says `RSYSCALL_UNIX_STUB_SOCK`. It is also unclear whether the stub should strip the variable from the envp it reports, and how it should handle socket paths over 108 bytes (Python works around long paths on its own bind side, `sys/un.py` L31-44).
9. **ssh details.** The "4 times" comment is stale (the code connects twice); Python assumes accept order equals connect order through `ssh -L`; the name of the second temp-dir socket used between the `socket` and `rsyscall` modes is never given; the `socket`-mode process must exit 0 (L208).
10. **Array counts and string contents.** The array count is not on the wire; it comes from the struct field, whatever `read_length_prefixed_array`'s docstring says. String lengths must not include a NUL. Python's behaviour on EOF in the middle of a string is buggy (`epoller.py` L772-776).
11. **Error range.** Python treats `-4095 < r < 0` as an error, so it excludes -4095, which the kernel convention includes.
12. **fd passing.** The 1-byte payload is uninitialized memory, so its value is unspecified. Control buffers must hold 3 fds (stdin), 4 (stub) and `count` (persistent), with an unpadded `cmsg_len`. It is unspecified whether received fds should be CLOEXEC or blocking; the syscall fd must be blocking for the `MSG_WAITALL` memory writes to work.
13. **Persistent handshake.** Python loops forever if the server hits EOF before sending all 8 reply bytes (L332-334). It is ambiguous who closes the old connection fds: the server (L143) or Python's GC (L404). Handling of a `count` that doesn't match the number of passed fds is undefined.
14. **stdio in bootstrapped processes.** fds 0/1/2 are assumed to be stdio. For the stdin bootstrap, fd 0 is the socket that is already at EOF; whether the native side should replace it is unspecified.
15. **Stack size.** Native code gets about 4 KiB of stack with no guard page (`clone.py` L61, L114). A spec should state the stack budget.
