# rsyscall-ng v0: bootstrap handshakes (normative)

Status: v0, normative. This document specifies how a server that is not cloned in-process is
found and described to the client: the three helper executables `rsyscall-bootstrap` (ssh),
`rsyscall-stdin-bootstrap` and `rsyscall-unix-stub`, and the reconnection handshake of the
persistent server. Terms are defined in `README.md` §3; layouts come from
`abi-layouts.generated.md`; byte images from `vectors/v0.json`. After a handshake, the server
speaks `wire-protocol.md` on the syscall socket and obeys `native-abi.md`.

## 0. Common encodings

**Fixed-layout struct.** The client reads a describe struct by taking exactly `sizeof` bytes off
the data socket and copying them into a cdata of that type, so the receiver sees the native
x86-64 layout, padding included (`python/rsyscall/epoller.py:744-757`). A sender MUST write the
struct as its exact in-memory image with the sizes 56 (`struct rsyscall_bootstrap`), 64
(`struct rsyscall_stdin_bootstrap`) and 80 (`struct rsyscall_unix_stub`) of
`abi-layouts.generated.md` (`python/ffibuilder.py:1261-1288`); padding bytes SHOULD be zero and
MUST be ignored by the receiver (`python/rsyscall/epoller.py:744-757`). Field values are read with
the cdef types: `int` fields are signed 32-bit, `size_t`/`uint64_t` fields 64-bit, pointers 64-bit
(`python/ffibuilder.py:1261-1288`).

**Length-prefixed string.** A string is a `size_t` (8 bytes, native byte order, so little-endian)
byte count followed by exactly that many bytes; nothing is stripped, so the bytes MUST NOT include
a NUL terminator (`python/rsyscall/epoller.py:769-776`). The client splits environment entries on
the first `=` and decodes both halves with `os.fsdecode`; an entry without `=` makes the client
raise, so every envp entry MUST contain `=` (`python/rsyscall/epoller.py:785-801`). Vector
`lp_string` shows `PATH=/bin`.

**Counts.** Array counts are never on the wire: the number of strings to read comes from the struct
fields `envp_count` and `argc`, whatever the docstring of `read_length_prefixed_array` says
(`python/rsyscall/epoller.py:778-783`, `python/rsyscall/tasks/ssh.py:267`,
`python/rsyscall/tasks/stdin_bootstrap.py:99`, `python/rsyscall/tasks/stub.py:140-142`). A
sender MUST write exactly `argc` then `envp_count` strings, in that order, and MUST NOT prefix the
arrays with a count (`python/rsyscall/epoller.py:778-783`).

**Line-oriented text.** Where the client reads lines it splits on `\n` and strips only that byte,
comparing the rest verbatim (`python/rsyscall/epoller.py:803-826`, `python/rsyscall/tasks/ssh.py:201-204`).
A line MUST end with exactly one `\n` and MUST NOT contain `\r` (`python/rsyscall/epoller.py:821-826`).

**The client's SCM_RIGHTS message.** Every fd transfer from the client is one `sendmsg` with a
single 1-byte iovec whose content is uninitialised memory, and one control message
(`python/rsyscall/tasks/stdin_bootstrap.py:87-90`, `python/rsyscall/tasks/stub.py:128-131`,
`python/rsyscall/tasks/persistent.py:324-326`, `python/rsyscall/sys/uio.py:40-47`). The control
message is `struct cmsghdr { cmsg_len = 16 + 4n; cmsg_level = SOL_SOCKET; cmsg_type = SCM_RIGHTS }`
followed by `n` native `int` fd numbers, with no `CMSG_ALIGN` padding, and `msg_controllen` equals
the same `16 + 4n` (`python/rsyscall/sys/socket.py:304-314`, `python/rsyscall/sys/socket.py:328-329`,
`python/rsyscall/sys/socket.py:362-368`, `python/rsyscall/sys/socket.py:389-398`); vectors
`scm_rights_2fds`, `scm_rights_3fds` (28 bytes) and `scm_rights_4fds`. The fds appear in the
order of the list the client passes, and the receiver MUST assign meanings positionally
(`python/rsyscall/sys/socket.py:328-329`). A receiver MUST receive the message with `recvmsg`
using a control buffer of at least `CMSG_SPACE(4n)` bytes for the number `n` of fds it expects,
MUST consume the single payload byte and ignore its value, and SHOULD treat `MSG_CTRUNC` as a
fatal error (`python/rsyscall/tasks/stdin_bootstrap.py:87-90`, `python/rsyscall/tasks/stub.py:128-131`).

Rationale: the client comments its own encoding with "TODO is this correct alignment/padding???"
(`python/rsyscall/sys/socket.py:365-366`); the kernel accepts the unpadded form and re-encodes the
control data for the receiver, so the receiver's buffer needs the kernel's padded size, not the
sender's. `evolution-notes.md` lists the padding as a candidate change.

**Received file descriptors.** The syscall socket passed to a server is the remote side of a
`socketpair` channel and is blocking by construction, because only the access side is switched
to `O_NONBLOCK` (`python/rsyscall/network/connection.py:137-153`); the receiver MUST NOT make it
non-blocking (`wire-protocol.md` §1; `python/rsyscall/tasks/connection.py:164-167`). Whether
received fds carry `FD_CLOEXEC` is Unspecified in v0 (Recommended default: receive with
`MSG_CMSG_CLOEXEC`, as the client itself always does, `python/rsyscall/sys/socket.py:578`). The
received fd numbers are what the describe struct MUST report (`python/rsyscall/tasks/stdin_bootstrap.py:115`,
`python/rsyscall/tasks/stub.py:157`).

Rationale: Observed (black-box): in the four `probe_oracle.py` runs quoted in `wire-protocol.md`
§3 (modes `stdin`, `stub`, `stublong`, `bootstrap`; commands in `README.md` §4) the oracle
executables received the message with `recvmsg(fd, {1-byte iov, control buffer}, MSG_CMSG_CLOEXEC)`,
the kernel reported `msg_controllen` 32 for 3 fds and 32 for 4 fds, and the received fds carried
`FD_CLOEXEC` while fds 0, 1 and 2 did not.

## 1. In-process clone server

A server started by `Process.clone`/`fork` has no handshake: the client opens one channel, puts the
remote-side socket into the stack image as both arguments of `rsyscall_server`, and clones
(`python/rsyscall/tasks/clone.py:103-105`, `python/rsyscall/tasks/clone.py:107-114`,
`python/rsyscall/thread.py:276-278`). The pid comes from the return value of `clone`, the
symbols from the parent's loader (`python/rsyscall/tasks/clone.py:114`, `python/rsyscall/thread.py:278`,
`python/rsyscall/tasks/local.py:109`), and the connection is
`SyscallConnection(access_sock, remote_sock_handle)` (`python/rsyscall/tasks/clone.py:162-170`).
Such a server MUST NOT write anything before its first response and MUST NOT expect anything but
requests (`python/rsyscall/tasks/connection.py:213-291`); everything else is `wire-protocol.md`
and `native-abi.md` §3 to §6.

## 2. ssh bootstrap: `rsyscall-bootstrap`

**Install path.** The executable is `rsyscall-bootstrap`, resolved by `rsyscall._native.helper`
(the copy bundled in `rsyscall/_native/`, or `$RSYSCALL_LIBEXEC_DIR/rsyscall-bootstrap`, i.e. the
prefix's `libexec/rsyscall/` in the development flow; `python/rsyscall/tasks/ssh.py:105`). The
client opens it read-only and ships it to the remote
host as the standard input of an `ssh` command whose remote script is
`python/rsyscall/tasks/ssh_bootstrap.sh` (`python/rsyscall/tasks/ssh.py:51`,
`python/rsyscall/tasks/ssh.py:161`, `python/rsyscall/tasks/ssh.py:186-188`):

```sh
dir="$(mktemp --directory)"
cat >"$dir/bootstrap"
chmod +x "$dir/bootstrap"
cd "$dir" || exit 1
echo "$dir"
exec "$dir/bootstrap" socket
```

Only that one file reaches the remote host, so `rsyscall-bootstrap` MUST be a single
self-contained executable (statically linked or otherwise free of run-time dependencies on the rest
of the installation) that works from an arbitrary temporary directory
(`python/rsyscall/tasks/ssh_bootstrap.sh:2-6`, `python/rsyscall/tasks/ssh.py:171-180`).

**Stage 1: `bootstrap socket`.** Run with argv `["<dir>/bootstrap", "socket"]` and cwd = the
temporary directory (`python/rsyscall/tasks/ssh_bootstrap.sh:4-6`). The client reads two lines
from the ssh stdout: the directory printed by the shell, then a line that MUST be exactly `done`
(`python/rsyscall/tasks/ssh.py:200-204`). Before printing `done\n`, the process MUST have created
an `AF_UNIX` `SOCK_STREAM` socket bound to `<dir>/data` and put it in the listening state, because
the client forwards `<dir>/data` and connects to it right after reading the two lines
(`python/rsyscall/tasks/ssh.py:247-262`). The `socket`-mode process MUST exit with status 0 once
the `rsyscall`-mode process holds the listening socket: the client checks its exit status after
the describe has been read and raises on anything but a clean exit
(`python/rsyscall/tasks/ssh.py:208`, `python/rsyscall/monitor.py:194-207`,
`python/rsyscall/sys/wait.py:91-92`). Both processes MUST NOT write anything to stdout after
`done\n`, since the client stops reading after the second line and OpenSSH does not close the
channel on EOF (`python/rsyscall/tasks/ssh.py:197-205`).

The hand-off of the listening socket from the `socket` process to the `rsyscall` process is
implementation-defined: the client only knows that "the main bootstrap process will connect to
[a second socket in the directory], to grab the listening socket fd" (`python/rsyscall/tasks/ssh.py:171-180`).
Any file the implementation creates for this purpose MUST NOT be named `bootstrap` or `data`
(`python/rsyscall/tasks/ssh_bootstrap.sh:2`, `python/rsyscall/tasks/ssh.py:248`), and its name is
Unspecified in v0 (Recommended default: `<dir>/pass`, removed once the hand-off is complete).

Rationale: Observed (black-box): `probe_oracle.py ... bootstrap` (command in `README.md` §4)
showed the oracle's `socket` mode binding and listening on `./data` and on `./pass` (both with
backlog 10), writing `done\n`, closing stdout, accepting one connection on `pass`, unlinking
`./pass`, sending the `data` listening socket over it with `SCM_RIGHTS`, and exiting 0; the
`rsyscall` mode connected to `./pass` and received that fd with `recvmsg`.

**Stage 2: forwarding.** The client runs `ssh -L ./<name>:<dir>/data -n "echo forwarded; exec sleep 60"`
and waits for the line `forwarded`; it then connects to the local end of the tunnel
(`python/rsyscall/tasks/ssh.py:210-230`, `python/rsyscall/tasks/ssh.py:243-248`). The native
side is not involved beyond keeping `<dir>/data` accepting connections (`python/rsyscall/tasks/ssh.py:248`).

Rationale: the client assumes that connections are accepted in the order it opened them; with
`ssh -L` each local connection becomes one remote connection made by `sshd`, and the client
opens the second only after the first `connect` completed (`python/rsyscall/tasks/ssh.py:257-262`).
This is an environmental assumption, not something the native side can enforce.

**Stage 3: `bootstrap rsyscall`.** Run as `cd <dir>; exec ./bootstrap rsyscall`
(`python/rsyscall/tasks/ssh.py:250-253`). It MUST obtain the listening socket from stage 1 and
MUST accept exactly two connections on it, in order: the first is the syscall socket, the second
the data socket (`python/rsyscall/tasks/ssh.py:256-262`, `python/rsyscall/tasks/ssh.py:264-265`,
`python/rsyscall/tasks/ssh.py:281-286`). It MUST then write on the data socket the 56-byte
`struct rsyscall_bootstrap` followed by `envp_count` length-prefixed environment entries (§0),
and MUST complete that write before blocking on the syscall socket, because the client reads the
describe before it sends its first request (`python/rsyscall/tasks/ssh.py:263-267`,
`python/rsyscall/tasks/ssh.py:281-292`). After that it MUST run `rsyscall_server` on the syscall
socket as `infd` and `outfd` (`python/rsyscall/tasks/ssh.py:281-286`, `wire-protocol.md` §1).

| field | meaning | source |
|---|---|---|
| `symbols` | absolute addresses of the four entry points in this process (`native-abi.md` §8) | `python/rsyscall/tasks/ssh.py:303` |
| `pid` | the pid of this process; the client uses it as the task pid and as the identity of its address space, pid namespace and mount namespace | `python/rsyscall/tasks/ssh.py:266`, `python/rsyscall/tasks/ssh.py:269-280` |
| `listening_sock` | fd number of the listening socket, which MUST stay open and unused by the native side: the client sets `O_NONBLOCK` on it and accepts further connections through syscalls | `python/rsyscall/tasks/ssh.py:288`, `python/rsyscall/tasks/ssh.py:293-299`, `python/rsyscall/network/connection.py:187-196` |
| `syscall_sock` | fd number of the first accepted connection, on which the server runs | `python/rsyscall/tasks/ssh.py:281-286` |
| `data_sock` | fd number of the second accepted connection, which MUST stay open and MUST NOT be used by the native side after the describe | `python/rsyscall/tasks/ssh.py:287`, `python/rsyscall/tasks/ssh.py:263-267` |
| `envp_count` | number of environment entries that follow | `python/rsyscall/tasks/ssh.py:267` |

The environment entries MUST be the process's own environment, each `KEY=value`, verbatim
(`python/rsyscall/tasks/ssh.py:267`, `python/rsyscall/tasks/ssh.py:306`,
`python/rsyscall/epoller.py:785-801`). File descriptors 0, 1 and 2 are taken by the client as the
process's stdin, stdout and stderr, so the `rsyscall`-mode process MUST leave them as inherited
from `sshd` (`python/rsyscall/tasks/ssh.py:307-309`). The client assumes an empty signal mask ("we
assume ssh zeroes the sigmask before starting us", `python/rsyscall/tasks/ssh.py:290`), so the
process MUST NOT block any signal before or while serving (`python/rsyscall/tasks/ssh.py:290-292`).
The first requests the client sends are a 4 GiB `mmap`, `epoll_create` and a `SIGCHLD` signalfd
(`python/rsyscall/tasks/ssh.py:289-292`).

Rationale: Observed (black-box): the oracle's `rsyscall` mode additionally called
`readlinkat("/proc/self/exe")` and `prctl(PR_SET_PDEATHSIG, SIGKILL)`, accepted with
`accept4(..., SOCK_CLOEXEC)`, wrote the 56-byte struct in one `write` and each string as two
writes (length, bytes), and on EOF of the syscall socket printed
`rsyscall-bootstrap: rsyscall_server(syscall_sock, syscall_sock): Success` to stderr and exited 1;
`<dir>/data` was left in place. None of this is required by `python/`.

## 3. stdin bootstrap: `rsyscall-stdin-bootstrap`

**Install path and invocation.** The executable is `rsyscall-stdin-bootstrap`, resolved by
`rsyscall._native.helper` (the copy bundled in `rsyscall/_native/`, or
`$RSYSCALL_LIBEXEC_DIR/rsyscall-stdin-bootstrap`, i.e. the prefix's `libexec/rsyscall/` in the
development flow; `python/rsyscall/tasks/stdin_bootstrap.py:54`). It is exec'd by an arbitrary
command that passes
its stdin down, e.g. `Command(path, ['rsyscall-stdin-bootstrap'], {})` or `sudo <path>`
(`python/rsyscall/tasks/stdin_bootstrap.py:1-9`, `python/rsyscall/tests/test_stdinboot.py:16-18`);
it MUST work when started with `argv[0]` alone (`python/rsyscall/tests/test_stdinboot.py:17`);
its behaviour when given additional arguments is Unspecified in v0 (Recommended default: ignore
them). Its fd 0 is one end of an
`AF_UNIX SOCK_STREAM` `socketpair` created by the client (`python/rsyscall/tasks/stdin_bootstrap.py:72-78`).

**Handshake.** The process MUST receive on fd 0 exactly one SCM_RIGHTS message (§0) carrying, in
order, the syscall socket, the data socket and the connection fd
(`python/rsyscall/tasks/stdin_bootstrap.py:83-90`). The client closes its end right after
sending, so fd 0 then reaches EOF; the process MUST NOT wait for or expect any further input on fd 0
(`python/rsyscall/tasks/stdin_bootstrap.py:91-95`). It MUST then write on the data socket the
64-byte `struct rsyscall_stdin_bootstrap` followed by `envp_count` environment entries (§0), and
complete that write before blocking on the syscall socket (`python/rsyscall/tasks/stdin_bootstrap.py:97-99`,
`python/rsyscall/tasks/stdin_bootstrap.py:115-121`), then run `rsyscall_server` on the syscall
socket as `infd` and `outfd` (`python/rsyscall/tasks/stdin_bootstrap.py:115-120`).

| field | meaning | source |
|---|---|---|
| `symbols` | absolute addresses of the four entry points in this process | `python/rsyscall/tasks/stdin_bootstrap.py:131` |
| `pid` | this process's pid; the client assumes the pid namespace is shared with the parent | `python/rsyscall/tasks/stdin_bootstrap.py:101-113` |
| `syscall_fd` | number of the first received fd, on which the server runs | `python/rsyscall/tasks/stdin_bootstrap.py:115-120`, `python/rsyscall/tasks/stdin_bootstrap.py:83-84` |
| `data_fd` | number of the second received fd; MUST stay open and MUST NOT be used after the describe | `python/ffibuilder.py:1273`, `python/rsyscall/tasks/stdin_bootstrap.py:83-84` |
| `futex_memfd` | Unspecified in v0 (Recommended default: -1); only three fds are passed and the client never reads the field | `python/rsyscall/tasks/stdin_bootstrap.py:88-89`, `python/ffibuilder.py:1274` |
| `connecting_fd` | number of the third received fd; it becomes the process's `FDPassConnection` fd, on which the client itself later performs `recvmsg`, so it MUST stay open and MUST NOT be read or written natively | `python/rsyscall/tasks/stdin_bootstrap.py:126-127`, `python/rsyscall/network/connection.py:116-135` |
| `envp_count` | number of environment entries that follow | `python/rsyscall/tasks/stdin_bootstrap.py:99` |

The environment entries MUST be the process's own environment, verbatim
(`python/rsyscall/tasks/stdin_bootstrap.py:99`, `python/rsyscall/tasks/stdin_bootstrap.py:134`).
Fds 0, 1 and 2 are taken as stdin, stdout and stderr (`python/rsyscall/tasks/stdin_bootstrap.py:135-137`):
fd 1 and fd 2 MUST be left as inherited, and fd 0, the handshake socket at EOF, MUST remain
open as fd 0 and MUST NOT be replaced or closed by the native side
(`python/rsyscall/tasks/stdin_bootstrap.py:135`). The client assumes the signal mask is empty
("we assume our SignalMask is zero'd before being started", `python/rsyscall/tasks/stdin_bootstrap.py:122`),
so the process MUST NOT block any signal (`python/rsyscall/tasks/stdin_bootstrap.py:122-125`).

Rationale: Observed (black-box): `probe_oracle.py ... stdin` (command in `README.md` §4): the
oracle reported `futex_memfd = 0`, zero padding at offset 52, the environment verbatim including
an entry with an empty value, kept fd 0 as the (EOF) handshake socket, left an inherited blocked
`SIGUSR1` in place, wrote the struct in one 64-byte `write`, and exited 0 on EOF of the syscall
socket.

## 4. Unix stub: `rsyscall-unix-stub`

**Install path and environment variable.** The executable is `rsyscall-unix-stub`, resolved by
`rsyscall._native.helper` (the copy bundled in `rsyscall/_native/`, or
`$RSYSCALL_LIBEXEC_DIR/rsyscall-unix-stub`, i.e. the prefix's `libexec/rsyscall/` in the
development flow; `python/rsyscall/tasks/stub.py:91`). It MUST
read the socket path from the environment variable `RSYSCALL_UNIX_STUB_SOCK_PATH`
(`python/rsyscall/tasks/stub.py:96-98`; the module docstring names the same variable,
`python/rsyscall/tasks/stub.py:7-8`). The client writes a
wrapper script with mode 0755 (`python/rsyscall/tasks/stub.py:94-99`):

```sh
#!/bin/sh
RSYSCALL_UNIX_STUB_SOCK_PATH={sock} exec {bin} "$0" "$@"
```

so the stub's argv is `[<bin>, <wrapper $0>, <user arguments>...]`. The stub MUST report its
complete argv including `argv[0]` (`argc` entries); the client drops the first entry itself and
returns the rest (`python/rsyscall/tasks/stub.py:111-114`, `python/rsyscall/tasks/stub.py:140-141`).
Arguments MUST be reported verbatim, including empty strings (`python/rsyscall/tasks/stub.py:140-141`,
`python/rsyscall/epoller.py:769-776`).

**Listener and connection.** The client listens with an `AF_UNIX` `SOCK_STREAM|SOCK_NONBLOCK`
socket bound to the path and `listen(10)` (`python/rsyscall/tasks/stub.py:78-84`). The stub MUST
connect an `AF_UNIX` `SOCK_STREAM` socket to that path (`python/rsyscall/tasks/stub.py:80-83`,
`python/rsyscall/tasks/stub.py:111`). Paths of up to 107 bytes MUST work
(`python/rsyscall/sys/un.py:27-29`); longer paths are Unspecified in v0 (Recommended default: open
the path with `O_PATH` and connect to `/proc/self/fd/<n>`, the same workaround the client uses for
its own bind, `python/rsyscall/sys/un.py:31-44`).

**Handshake.** On the connection the stub MUST receive exactly one SCM_RIGHTS message (§0)
carrying, in order, the syscall socket, the data socket, a memfd and the connection fd
(`python/rsyscall/tasks/stub.py:121-131`). It MUST then write on the data socket the 80-byte
`struct rsyscall_unix_stub`, then `argc` argument strings, then `envp_count` environment entries
(§0), completing them before blocking on the syscall socket, and then run `rsyscall_server` on the
syscall socket (`python/rsyscall/tasks/stub.py:138-142`, `python/rsyscall/tasks/stub.py:157-163`).
The client closes its end of the connection socket after sending; whether the stub closes its own
end is Unspecified in v0 (Recommended default: close it) (`python/rsyscall/tasks/stub.py:136`).

| field | meaning | source |
|---|---|---|
| `symbols` | absolute addresses of the four entry points in this process | `python/rsyscall/tasks/stub.py:174` |
| `pid` | this process's pid; pid namespace assumed shared | `python/rsyscall/tasks/stub.py:144-151` |
| `syscall_fd` | number of the first received fd, on which the server runs | `python/rsyscall/tasks/stub.py:157-162` |
| `data_fd` | number of the second received fd; MUST stay open and MUST NOT be used after the describe | `python/ffibuilder.py:1282`, `python/rsyscall/tasks/stub.py:121-122` |
| `futex_memfd` | MUST be the number of the third received fd (the memfd named `child_robust_futex_list`); the client records it and does not use it yet | `python/rsyscall/tasks/stub.py:124-125`, `python/rsyscall/tasks/stub.py:129-130`, `python/rsyscall/tasks/stub.py:182-183` |
| `connecting_fd` | number of the fourth received fd; the client's `FDPassConnection` fd, so it MUST stay open and MUST NOT be read or written natively | `python/rsyscall/tasks/stub.py:169-170`, `python/rsyscall/network/connection.py:116-135` |
| `argc` | number of argument strings that follow | `python/rsyscall/tasks/stub.py:140` |
| `envp_count` | number of environment entries that follow the arguments | `python/rsyscall/tasks/stub.py:142` |
| `sigmask` | the process's blocked-signal mask as a 64-bit set: bit `n-1` set means signal `n` is blocked | `python/rsyscall/tasks/stub.py:164`, `python/rsyscall/struct.py:100-105`, `python/rsyscall/signal.py:127-131` |

**Signal mask.** The client seeds its mask tracking from `sigmask` (`python/rsyscall/tasks/stub.py:164`)
and then blocks `SIGCHLD` for its child monitor (`python/rsyscall/tasks/stub.py:168`,
`python/rsyscall/monitor.py:254`, `python/rsyscall/monitor.py:97-102`): it raises if `SIGCHLD` is
already in the reported set (`python/rsyscall/signal.py:279-283`) and raises if the mask the kernel
returns as the old set is not a superset of the reported set (`python/rsyscall/signal.py:290-304`).
The reported `sigmask` therefore MUST be a subset of the signals actually blocked at the time
the client's first `sigprocmask` runs, MUST NOT include `SIGCHLD`, and SHOULD equal the actual
mask; if the stub inherited a mask with `SIGCHLD` blocked it MUST unblock `SIGCHLD` before
serving (`python/rsyscall/signal.py:281-283`, `python/rsyscall/signal.py:302-304`). The mapping
`bit n-1 = signal n` follows the kernel's `sigset_t`; vector `sigmask_sigchld` shows `0x10000`
decoding to signal 17 (`python/rsyscall/signal.py:129-130`, `python/rsyscall/struct.py:100-105`).

The environment entries MUST be the process's own environment, verbatim; whether the
`RSYSCALL_UNIX_STUB_SOCK_PATH` entry is included is Unspecified in v0 (Recommended default: do not
strip it) (`python/rsyscall/tasks/stub.py:142`, `python/rsyscall/tasks/stub.py:177`). Fds 0, 1
and 2 MUST be left exactly as inherited from the program that launched the stub: they are the
whole point of the stub ("stdin pointing to some email message") and the client reads them
(`python/rsyscall/tasks/stub.py:20-25`, `python/rsyscall/tasks/stub.py:178-180`,
`python/rsyscall/tests/test_stub.py:40-50`).

Rationale: Observed (black-box): `probe_oracle.py ... stub` and `... stublong` (commands in
`README.md` §4): the oracle opened the socket path with `O_PATH|O_CLOEXEC` and connected to
`/proc/self/fd/<n>` (this also worked for a 133-byte path), received four fds with
`MSG_CMSG_CLOEXEC`, read its mask with `rt_sigprocmask` and reported `0x200` for an inherited
blocked `SIGUSR1`, reported `futex_memfd` = the third received fd, argv with `argv[0]` and an
empty argument intact, the environment verbatim including `RSYSCALL_UNIX_STUB_SOCK_PATH=...`, kept
its connection socket open, and exited 0 on EOF of the syscall socket.

## 5. Persistent server

**Creation.** The client creates the listening socket itself: `socket(AF_UNIX, SOCK_STREAM)`
(the client adds `SOCK_CLOEXEC`), `bind` to the chosen path, `listen(1)`
(`python/rsyscall/tasks/persistent.py:286-288`, `python/rsyscall/sys/socket.py:618`). It then
clones a child with `CLONE_FILES|CLONE_FS|CLONE_SIGHAND` plus the mandatory flags, whose stack
image calls `rsyscall_persistent_server(sock, sock, listening_sock)`
(`python/rsyscall/tasks/persistent.py:289-292`, `python/rsyscall/tasks/clone.py:99-101`). The
listening socket is blocking; the server MUST NOT change its flags or `bind`/`listen` again
(`python/rsyscall/tasks/persistent.py:286-288`). Making the process persistent is done by the
client with ordinary syscalls (`unshare(CLONE_FILES)` and a userspace cloexec sweep, `setsid`,
`prctl(PR_SET_PDEATHSIG, 0)`); no native behaviour is involved
(`python/rsyscall/tasks/persistent.py:364-375`).

**Disconnect.** The client disconnects with `shutdown(SHUT_WR)` on its access socket
(`python/rsyscall/tasks/persistent.py:140-148`, `python/rsyscall/tasks/persistent.py:392`). The
server MUST finish the request in progress and write its response, then, on EOF of `infd`, MUST
stop using the connection, MUST make its end unusable for the peer (by `shutdown` or `close`) and
MUST go back to accepting on `listensock` (`python/rsyscall/tasks/persistent.py:141-144`).
Whether the old fd is closed by the server or merely shut down is Unspecified in v0, because the
client closes leftover fds by garbage collection after reconnecting ("close remote fds we don't
have handles to; this includes the old interface fds", `python/rsyscall/tasks/persistent.py:404-405`)
(Recommended default: `shutdown(SHUT_RDWR)` on `infd` and `outfd` and leave the fds to the
client). The server MUST NOT exit on disconnect (`python/rsyscall/tasks/persistent.py:7-8`).

**Reconnection handshake.** On the new connection accepted from `listensock`, the client sends,
in order (`python/rsyscall/tasks/persistent.py:312-338`):

| step | direction | bytes | content | source |
|---|---|---|---|---|
| 1 | client to server | 4 | native `int32` count of fds that follow (2 today; vector `persistent_count`) | `python/rsyscall/tasks/persistent.py:323`, `python/rsyscall/tasks/persistent.py:330`, `python/rsyscall/struct.py:108-123` |
| 2 | client to server | 1 + cmsg | one SCM_RIGHTS message (§0) with `count` fds: the new syscall socket then the new data socket | `python/rsyscall/tasks/persistent.py:319`, `python/rsyscall/tasks/persistent.py:324-326`, `python/rsyscall/tasks/persistent.py:331` |
| 3 | server to client | 4 x count | the fd numbers the server received, as native `int32`, in the same order (vector `persistent_reply`) | `python/rsyscall/tasks/persistent.py:327`, `python/rsyscall/tasks/persistent.py:332-336` |
| 4 | client | | closes the connection | `python/rsyscall/tasks/persistent.py:337` |

The server MUST read exactly 4 bytes for step 1 before calling `recvmsg`, MUST receive exactly one
message in step 2, and MUST reply with exactly `count` `int32` values in received order, because
the client loops until `4 * count` bytes have arrived and never times out
(`python/rsyscall/tasks/persistent.py:330-336`). The first number becomes the client's new
`server_fd`, so fd[0] MUST be the server's new `infd` and `outfd`; the second is wrapped in a
handle and closed later by the client, so fd[1] MUST stay open and unused by the native side
(`python/rsyscall/tasks/persistent.py:335-336`, `python/rsyscall/tasks/persistent.py:394-402`).
After step 3 the server MUST close its accepted connection fd and serve `wire-protocol.md` on fd[0]
(`python/rsyscall/tasks/persistent.py:337`, `python/rsyscall/tasks/persistent.py:398-402`).
A `count` that does not match the number of fds actually received is Unspecified in v0
(Recommended default: close the received fds and the connection, and keep listening).

Rationale: Observed (black-box): in the `probe_persistent3.py` run quoted in `wire-protocol.md`
§10 the oracle did `read(conn, 4)`, `recvmsg(conn, ..., MSG_CMSG_CLOEXEC)`, `write(conn, 8 bytes)`,
`close(conn)`, then served on fd[0]; on EOF it issued `shutdown(fd, SHUT_RDWR)` twice (once for
`infd`, once for `outfd`) without closing, then `accept4(listensock, NULL, NULL, SOCK_CLOEXEC)`.
With `count = 1` and two fds it replied one number and kept serving; with `count = 3` and two fds
it printed `Message has wrong controllen` and exited 1.

**Exit and the socket path.** After the client's `exit(0)` request the process is gone but the
socket path remains, and a reconnection attempt fails with `ECONNREFUSED`, which the test-suite
expects (`python/rsyscall/tests/test_persistent.py:41-48`). The server MUST NOT unlink the socket
path at any point, neither at start-up, nor on disconnect, nor when it stops
(`python/rsyscall/tests/test_persistent.py:46-48`, `python/rsyscall/tasks/persistent.py:286-288`).

Python-side behaviour: syscalls issued while disconnected block until the reconnection completes;
`SyscallSendError` is retried on the new connection and `SyscallHangup` is surfaced to the user
(`python/rsyscall/tasks/persistent.py:10-14`, `python/rsyscall/tasks/persistent.py:198-260`).
Before reconnecting, the client may call `prep_for_reconnect`, which unshares the fd table and
closes cloexec fds in userspace, because fds "opened by the C code running in the process will
leak if the process is in a shared fd table" (`python/rsyscall/tasks/persistent.py:364-369`,
`python/rsyscall/tasks/persistent.py:381-388`).

## 6. Failure conventions of the executables

How a helper executable reports a failed handshake (missing environment variable, bad argument,
`recvmsg` on a non-socket, connection failure) is Unspecified in v0 (Recommended default: exit
with a non-zero status after writing a one-line diagnostic prefixed with the program name to
stderr, and never write anything to stdout). The only exit status the client checks is that of
the `socket`-mode bootstrap, which MUST be 0 in the successful case (`python/rsyscall/tasks/ssh.py:208`,
`python/rsyscall/monitor.py:194-207`, `python/rsyscall/sys/wait.py:91-92`). The exit status of
a stdin bootstrap or stub process that ends because its syscall socket reached EOF is only waited
for, never checked (`python/rsyscall/tests/test_stdinboot.py:22-23`), and is Unspecified in v0
(Recommended default: 0).

Rationale: Observed (black-box), commands in `README.md` §4: with no arguments and no
environment, `rsyscall-bootstrap` printed `rsyscall-bootstrap: usage: <path> <type>` and exited 1;
with an unknown mode it printed `rsyscall-bootstrap: unknown type bogus` and exited 1; in
`rsyscall` mode without a preceding `socket` mode it printed `rsyscall-bootstrap: bind: No such file or directory`
and exited 1; `rsyscall-stdin-bootstrap` with `/dev/null` as stdin printed
`rsyscall-stdin-bootstrap: recvmsg(sock=0): Socket operation on non-socket` and exited 1;
`rsyscall-unix-stub` without the variable printed
`rsyscall-unix-stub: missing environment variable RSYSCALL_UNIX_STUB_SOCK_PATH: Success` and
exited 1, and with a non-existent path `rsyscall-unix-stub: bind: No such file or directory`,
exit 1. On EOF of the syscall socket the stdin bootstrap and the stub exit 0, the ssh bootstrap
exits 1 with a message (§2).
