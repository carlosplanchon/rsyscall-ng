# Evolution notes (non-normative)

This document binds nothing. It collects the changes a later protocol version could make, the
Python-side defects noticed while deriving v0, and the gaps of the differential oracle. Nothing
here is a requirement; the requirements are in `wire-protocol.md`, `native-abi.md` and
`bootstrap-handshakes.md`.

## Versioning and hello

- v0 has no version marker anywhere: the first bytes on a syscall socket are already a request
  (`wire-protocol.md` §1). A v1 could begin every connection with a fixed hello (magic, version,
  capability bits) or export a differently named entry point, so that a client can detect which
  protocol a server speaks. The describe structs are similarly unversioned; a `version` field at
  the start of `struct rsyscall_symbol_table` would cover the bootstraps too.

## Architecture neutrality

- The stack image names x86-64 registers (`python/ffibuilder.py:1241-1249`) but is really "six
  integer arguments plus a target": a neutral layout would call the slots `arg0..arg5`, keep the
  same offsets, and let each architecture's trampoline map them to its argument registers.
- An aarch64 mapping of the same 64-byte image: `x0..x5` from offsets +8..+48, the target from
  +56. The entry mechanism differs: on x86-64 the cloned child pops the trampoline address with
  `ret` (`native-abi.md` §3.5), whereas on aarch64 `ret` returns through `x30`, so the raw
  syscall primitive in the child would instead load the trampoline address from `[sp]` and branch
  to it. The `clone` wrapper on aarch64 also takes its arguments in a different order than the
  x86-64 raw syscall.
- The describe structs are parsed with the client's own `ffi` (`native-abi.md` §1). Mixed-ABI
  deployments over ssh would need either a fixed cross-platform encoding (explicit little-endian
  fixed-width fields) or a per-host `ffi`.

## Stacks, TLS and clone flags

- The 4096-byte stack without a guard page (`native-abi.md` §4) is small for anything but
  hand-written code. A larger allocation with a `PROT_NONE` guard page below it would turn an
  overflow into a crash of the child instead of silent corruption of the shared address space.
- `newtls` is always 0 (`python/rsyscall/sched.py:149-150`), so the child has no TLS of its own.
  Passing `CLONE_SETTLS` with a per-child TLS block would allow trampoline-entered code to be
  ordinary compiled code (including `errno` and Rust's thread-local machinery).
- The futex helper's stack is never freed (`python/rsyscall/tasks/clone.py:69`). Because the
  helper stops itself before touching the futex, the client could free it after the stop, or the
  helper could be replaced by something that needs no stack at all.

## Futex helper

- The cdef declares one parameter but the client passes two (`native-abi.md` §3.4). Declaring
  `void rsyscall_futex_helper(uint32_t *addr, uint32_t expected)` would make the ABI honest.
- `EINTR` handling and spurious wake-ups are unspecified in v0. A v1 could require a re-check of
  the futex word and a loop, and define the exit status.
- The `SIGSTOP`/`SIGCONT` dance only exists to tell the client that the helper has finished
  reading its stack. A pipe, an eventfd or a flag word written by the helper would give the same
  signal without job-control semantics and would let the helper run under a debugger.

## Wire protocol

- Request ids would allow out-of-order completion and concurrent servers; batching several
  requests behind one length field would cut the number of `read` calls. The current docstring
  already promises batching that the code does not do (`python/rsyscall/tasks/connection.py:7-9`).
- Arguments and results are signed `int64` (`wire-protocol.md` §2, §4). Unsigned 64-bit
  arguments are representable only through their two's-complement image; an explicit unsigned
  encoding would remove the ambiguity for values with the top bit set.
- The client treats `-4095 < r < 0` as an error (`python/rsyscall/near/sysif.py:206-210`), which
  excludes -4095 while the kernel's error range includes it. A future client could use
  `-4096 < r < 0`.

## Bootstraps

- The SCM_RIGHTS control buffer is written without `CMSG_ALIGN` padding and the client says so
  ("TODO is this correct alignment/padding???", `python/rsyscall/sys/socket.py:365-366`). A v1
  client would pad to `CMSG_SPACE`.
- The 1-byte payload of every fd-passing message is uninitialised memory
  (`python/rsyscall/tasks/stdin_bootstrap.py:87`, `python/rsyscall/tasks/stub.py:128`,
  `python/rsyscall/tasks/persistent.py:324`). Initialising it to 0 costs nothing.
- Array counts live in struct fields while the docstring of `read_length_prefixed_array` describes
  a count on the wire (`python/rsyscall/epoller.py:778-783`). Either the docstring or the
  encoding could change; putting counts on the wire would make the strings self-describing.
- `read_length_prefixed_string` swallows an `EOFError` raised while reading the bytes of a string:
  the `except` block sets the message but does not re-raise (`python/rsyscall/epoller.py:772-776`).
  A truncated describe therefore surfaces as a confusing later error instead of an `EOFError`.
- The `stub.py` module docstring used to name the environment variable `RSYSCALL_UNIX_STUB_SOCK`
  while the code sets `RSYSCALL_UNIX_STUB_SOCK_PATH` (`python/rsyscall/tasks/stub.py:97`); the
  docstring now names the same variable (`python/rsyscall/tasks/stub.py:7-8`).
- The comment "Connect to local socket 4 times" (`python/rsyscall/tasks/ssh.py:256`) is stale;
  the code connects twice.
- `PersistentSyscallConnection.read` relies on a stale `infallible_send`, issued on the connection
  that was just shut down, failing with `EPIPE` after a reconnection (`python/rsyscall/tasks/persistent.py:238-260`).
  Upstream requested that `sendto` with flags `0`, which kills a persistent process that has the
  default `SIGPIPE` disposition, i.e. one bootstrapped by a helper executable rather than cloned
  from CPython (which ignores `SIGPIPE`); `test_persistent.py::test_ssh_same` showed it with the Rust
  helpers and would with the C ones under the same timing. The client now requests it with
  `MSG_NOSIGNAL` (`python/rsyscall/tasks/connection.py:186`, `wire-protocol.md` §7); servers execute
  the flags verbatim, so the wire format is unchanged.
- `futex_memfd` is passed by the stub client and reported by two describe structs but never used
  (`python/rsyscall/tasks/stub.py:182-183`); dropping it (or defining what the memfd is for) would
  simplify the handshakes.
- No client path starts an `rsyscall-server` executable, although the oracle build checks for
  one (`scripts/oracle-build.sh`); the Rust implementation does not need to ship it.
- The helper executables were located through `rsyscall._nixdeps.librsyscall` via `rsyscall.nix`,
  which imported the `nixdeps` build hook at module level. They now come from `rsyscall._native`
  (the bundled copies, or `RSYSCALL_LIBEXEC_DIR`; `python/rsyscall/tasks/ssh.py:105`,
  `python/rsyscall/tasks/stdin_bootstrap.py:54`, `python/rsyscall/tasks/stub.py:91`), OpenSSH from
  `PATH` (`python/rsyscall/tasks/ssh.py:101`, `python/rsyscall/tasks/ssh.py:326-327`), and
  `rsyscall.nix` imports `nixdeps` only for type checking (`python/rsyscall/nix.py:25-26`), so the
  bootstrap tests run without a Nix store (see "Oracle gaps").

## Python-side defects noticed

- `python/rsyscall/unistd/exec.py:19-20` uses `AT.FDCWD` without importing `AT`; the branch is
  unreachable in the test-suite.
- `pyroute2` is imported (`python/rsyscall/linux/rtnetlink.py:2`) but was not declared as a
  dependency by the upstream `setup.py`; only the optional `test_net.py` notices. Since the
  packaging step the repository's `pyproject.toml` declares it as the optional extra `net`.
- The loop of a root epoller retried a `SyscallHangup` from `epoll_wait`, but not one from the
  `epoll_ctl` calls that move the registration of the activity fd to the connection made by a
  reconnection (`python/rsyscall/epoller.py:166-192`). The loop makes those calls lazily, once
  the previous `epoll_wait` returns, so they can still be in flight when the client asks the
  persistent process to `exit`. The hangup then escaped the loop into the coroutine that
  delivered it, the connection's response reader, and on through the local epoller into the
  trio system task that drives it, which stopped; the client hung. `examples/persistent.py`
  hung in 2 of 100 runs with the C oracle and 0 of 100 with the Rust side. The loop now retries
  those calls too, and counts a retried `DEL` that fails with `ENOENT`, or a retried `ADD` that
  fails with `EEXIST`, as done; `python/rsyscall/tests/test_epoller.py` loses each response on
  purpose (`TestActivityFdHangup`). The requests a server receives are unchanged.
- `Allocation.free` returns the whole pages that a freed allocation leaves empty with
  `MADV_REMOVE`, a request sent through the freeing task's connection without waiting for it
  (`python/rsyscall/memory/allocator.py:171-205`). Every task in an address space shares the
  allocator, and its finger allocates right next to the freed allocation, so until that request
  ran another task, the local interpreter for one, could allocate in those pages and write there,
  and the request then deleted the data. Syscall responses read into such a buffer came back as
  zero, which surfaced as `RuntimeError: somehow got a partial recv with MSG.WAITALL` (or `partial
  send`) or as a hang. The five tests that give a child a root epoller (`test_clone.py`,
  `test_epoller.py`) failed in 5 of 60 runs with the C oracle. The freed allocation now stretches
  over those pages until the request completes, so nothing is allocated there meanwhile, and they
  failed in none of 60; the pages are still returned with `MADV_REMOVE`.
- Every `SSHHost.ssh` left the bootstrap's temporary files behind for good
  (`python/rsyscall/tasks/ssh.py:149-163`). On the remote host that was the directory made by
  `ssh_bootstrap.sh`, holding a copy of `rsyscall-bootstrap` and the listening socket `data`. On
  the access host it was the socket the forwarding `ssh -L` listens on. Both sockets serve every
  later channel of the remote process tree, so they can only go once nothing holds their
  listeners. The client now unlinks the executable as soon as the describe has been read
  (`python/rsyscall/tasks/ssh.py:311`). It also starts a detached janitor on each host, a short
  `sh` script appended to the same file, that removes the sockets once their listeners are no
  longer listed in `/proc/net/unix`, and the remote directory once it is empty and no process uses
  it as its working directory. `ssh_bootstrap.sh`, the commands quoted in
  `bootstrap-handshakes.md` §2 and the wire format are unchanged, and remote processes still start
  in the temporary directory.

- Every clone left two things behind in the parent for the rest of its life: its end of the
  child's syscall connection, which the futex monitor shut down but never closed, and an 8 KiB
  `MAP_SHARED` mapping that nothing used, left over from the upstream refactor that moved the
  stack and the futex to the task's allocator. That is one socket and one mapping per process ever
  spawned (300 spawns: 300 more sockets, about 300 more mappings), so a long-lived parent runs out of file
  descriptors. The mapping is gone, and the monitor now closes the socket as well, once epoll has
  reported the hangup its shutdown causes (`python/rsyscall/tasks/clone.py:131-141`): taking the
  fd off the epollfd before that event would lose it, and with it the wakeup of whoever waits on
  the connection, exec included. `close_interface` leaves an already closed end alone
  (`python/rsyscall/tasks/connection.py:112-123`). A closed connection is no longer referenced by
  the epoller, so its loops are garbage-collected with the rest of the dead process; finalizers in
  that same garbage, such as `Pointer.__del__` returning memory, could then resume a finished
  loop (`RuntimeError: cannot reuse already awaited coroutine`, in `test_clone.py::test_nest_exec`),
  so a request made once a loop has ended fails with `SyscallSendError` instead
  (`python/rsyscall/tasks/connection.py:199-211`, `python/rsyscall/tasks/connection.py:213-217`,
  `python/rsyscall/tasks/connection.py:254-258`). `test_clone.py::TestCloneCleanup` checks that
  spawning leaves no fds and no mappings behind. The requests a server receives are unchanged.
- A child that has not exec'd outlives its parent. The futex helper of every clone shares the
  parent's fd table (`python/rsyscall/tasks/clone.py:61`), so when the parent dies the helper keeps
  the parent's end of the child's connection open: the child never sees end of file and the helper
  waits on a futex that is never woken. This is why interrupted tests leave pairs of such processes
  behind. Not changed: closing the child's own copy of that end does not help while the helper
  holds the table, and making clones die with their parent (`PR_SET_PDEATHSIG`, which
  `make_persistent` already resets) would change what every exec'd child does too.
- A child killed by a real-time signal made `waitid` handling raise `ValueError` from `SIG(status)`
  after the zombie had been reaped, losing its state for good (`SIG` only names the standard
  signals). `ChildState.sig` now holds the plain number for such a signal
  (`python/rsyscall/sys/wait.py:64`, `python/rsyscall/sys/wait.py:112-122`;
  `test_child.py::TestChild::test_killed_by_realtime_signal`).
- A failed `execve` left `Task.manipulating_fd_table` set, so the process could no longer get new
  fd handles, unlike `execveat` (`python/rsyscall/handle/__init__.py:288-289`); `exit` had the same
  shape (`python/rsyscall/handle/__init__.py:300-301`). Both reset it in a `finally` now
  (`test_child.py::TestChild::test_failed_exec_leaves_the_child_usable`).
- `Environment` cached two things it did not keep current: the `envp` array, reused by every
  later exec even after a variable changed, and the `PATH` lookups of `which`, which ignored a new
  `PATH`. Assigning `data`, item assignment and deletion now drop both
  (`python/rsyscall/environ.py:128-147`). `which` also searched `PATH` for names containing a
  slash; like `execvp`, it now takes them as paths (`python/rsyscall/environ.py:181-186`;
  `test_environ.py`).
- Every `SSHHost.ssh` left a zombie behind: the forwarding `ssh -L` was never waited for once it
  exited (`python/rsyscall/tasks/ssh.py:245-248`). It is reaped in the background now
  (`python/rsyscall/tasks/ssh.py:562-574`; `test_ssh.py::TestSSH::test_forwarder_reaped`).
- Misusing a `ChildPid` raised a plain `Exception`; waiting on or signalling a reaped child now
  raises `ChildDeadError`, and a concurrent use `ChildBusyError`, both subclasses of
  `ChildPidError` and of `Exception` (`python/rsyscall/handle/process.py:68-75`;
  `test_child.py::TestChild::test_signalling_a_reaped_child`).

## Oracle gaps

- Until the Nix coupling was removed, `tests/baseline-c.txt` exercised the in-process clone server,
  the futex helper and the trampoline through the core test modules, but none of the three helper
  executables and not the persistent server: `test_ssh.py`, `test_stdinboot.py`, `test_stub.py` and
  `test_persistent.py` were excluded from collection. They are collected now wherever `ssh`, `sshd`
  and `ssh-keygen` exist (`python/rsyscall/tests/conftest.py:19-29`, `tests/baseline-notes.md`), so
  the handshakes in `bootstrap-handshakes.md` §2 to §5 are backed by the recorded baselines as well
  as by the black-box observations listed in `README.md` §4; only `test_nix.py` and
  `test_ssh.py::test_nix_deploy` still need a Nix store.
