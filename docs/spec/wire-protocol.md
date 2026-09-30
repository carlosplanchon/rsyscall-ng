# rsyscall-ng v0: wire protocol (normative)

Status: v0, normative. This document defines the byte stream between the client and a server,
exactly as the Python client implements it today. Terms (client, server, syscall socket, data
socket, access side, remote side) are defined in `README.md` §3; every RFC 2119 statement cites
the `python/` lines that establish it. Struct layouts come from `abi-layouts.generated.md`;
byte-exact examples are in `vectors/v0.json` (§12).

## 1. Transport

The protocol runs over one byte stream per server. The client owns a `SyscallConnection` made of
its own non-blocking access-side socket `fd` and the number `server_fd` of the remote-side socket;
it sends requests on `fd` and reads responses from the same `fd`, so the server MUST read requests
from and write responses to one and the same stream (`python/rsyscall/tasks/connection.py:84-96`,
`python/rsyscall/tasks/connection.py:200`, `python/rsyscall/tasks/connection.py:229-236`).

The server receives the stream as two fd arguments, `infd` and `outfd` (`python/ffibuilder.py:1237`).
In every client path they are the same fd: the cloned server gets `[sock, sock]`
(`python/rsyscall/thread.py:276-278`), the persistent server `[sock, sock, listening_sock]`
(`python/rsyscall/tasks/persistent.py:292`), and the helper executables serve on the single
syscall fd they report (`python/rsyscall/tasks/ssh.py:281-286`,
`python/rsyscall/tasks/stdin_bootstrap.py:115-120`, `python/rsyscall/tasks/stub.py:157-162`).
An implementation MUST accept `infd == outfd` and MAY also accept two distinct fds.

The stream is an `AF_UNIX` `SOCK_STREAM` socket in every client path: a `socketpair` channel
(`python/rsyscall/network/connection.py:105`, `python/rsyscall/network/connection.py:137-143`) or
a connection accepted from a Unix listening socket (`python/rsyscall/network/connection.py:187-193`,
`python/rsyscall/tasks/ssh.py:257-262`). A server MUST work on such a socket; behaviour on other
stream types is Unspecified in v0 (Recommended default: treat any blocking byte stream that
supports `recvfrom`/`sendto` identically).

The remote side of a channel is deliberately left blocking: only the access side is switched to
`O_NONBLOCK` (`python/rsyscall/network/connection.py:149-150`). The server's fd MUST be in
blocking mode and the server MUST NOT switch it to non-blocking mode, because the client's memory
writes rely on a `recvfrom(..., MSG_WAITALL)` executed by the server completing in full; a short
result permanently breaks the connection (`python/rsyscall/tasks/connection.py:158-161`).

There is no header, no request id, no length field and no version negotiation: a request is a
fixed 56-byte struct and a response is a bare 64-bit integer
(`python/rsyscall/tasks/connection.py:3-5`, `python/rsyscall/tasks/connection.py:32-50`,
`python/rsyscall/tasks/connection.py:64-80`). Responses are matched to requests purely by order
through the client's `response_queue` (`python/rsyscall/tasks/connection.py:207`,
`python/rsyscall/tasks/connection.py:228-259`), so a server MUST NOT add, drop or reorder
responses.

Rationale: the client never sends anything that could identify a protocol version; a future
version needs a different entry point or an initial hello (see `evolution-notes.md`).

## 2. Request: `struct rsyscall_syscall`

A request is the 56-byte native image of `struct rsyscall_syscall` (`python/ffibuilder.py:1251-1254`,
`python/rsyscall/tasks/connection.py:34-38`, `python/rsyscall/tasks/connection.py:48-50`); the
layout is `abi-layouts.generated.md` § `struct rsyscall_syscall`. A server MUST interpret it as
seven little-endian two's-complement `int64` values:

| offset | size | field | content | source |
|---|---|---|---|---|
| 0 | 8 | `sys` | syscall number | `python/rsyscall/tasks/connection.py:36` |
| 8 | 8 | `args[0]` | first syscall argument | `python/rsyscall/tasks/connection.py:37` |
| 16 | 8 | `args[1]` | second argument | `python/rsyscall/tasks/connection.py:37` |
| 24 | 8 | `args[2]` | third argument | `python/rsyscall/tasks/connection.py:37` |
| 32 | 8 | `args[3]` | fourth argument | `python/rsyscall/tasks/connection.py:37` |
| 40 | 8 | `args[4]` | fifth argument | `python/rsyscall/tasks/connection.py:37` |
| 48 | 8 | `args[5]` | sixth argument | `python/rsyscall/tasks/connection.py:37` |

Arguments the caller does not supply are sent as 0 (`python/rsyscall/near/sysif.py:43`,
`python/rsyscall/tasks/connection.py:119-120`), and the client cannot tell the server how many
arguments a given syscall consumes, so the server MUST pass all six values to the kernel as the
six syscall arguments, in order, without inspecting the syscall number
(`python/rsyscall/tasks/connection.py:35-38`; the local backend does the same at
`python/rsyscall/tasks/local.py:36-38`).

Argument values are the caller's integers: file descriptors are sent as their numbers, pointers as
absolute addresses in the server's address space, flags and counts as plain integers, negative
values such as `AT_FDCWD` (-100) or `fd = -1` for anonymous `mmap` as two's-complement `int64`
(`python/rsyscall/tasks/local.py:55-58`, `python/rsyscall/unistd/exec.py:19-22`,
`python/rsyscall/sys/mman.py:121-126`). The server MUST NOT sign-extend, truncate or otherwise
rewrite argument values; it passes each 64-bit value as is (`python/rsyscall/tasks/connection.py:35-38`).

Example (vector `request_write`: `write(1, 0x1000, 12)`):

```
01 00 00 00 00 00 00 00   sys      = 1 (SYS_write)
01 00 00 00 00 00 00 00   args[0]  = 1
00 10 00 00 00 00 00 00   args[1]  = 0x1000
0c 00 00 00 00 00 00 00   args[2]  = 12
00 00 00 00 00 00 00 00   args[3]  = 0
00 00 00 00 00 00 00 00   args[4]  = 0
00 00 00 00 00 00 00 00   args[5]  = 0
```

## 3. Server loop

The server loop is: read one request, execute it, write its response, repeat.

**Framing.** The client writes each request with `send_all`, which retries partial sends, so a
request MAY arrive in several pieces and two requests MAY arrive in one piece
(`python/rsyscall/epoller.py:595-611`, `python/rsyscall/tasks/connection.py:200`). The server
MUST read exactly 56 bytes per request, accumulating short reads until the whole struct has
arrived (`python/rsyscall/tasks/connection.py:34-38`, `python/rsyscall/tasks/connection.py:48-50`).

**No read-ahead.** The bytes that follow a memory-write request are raw memory contents, not a
request (§5; `python/rsyscall/tasks/connection.py:163-168`, `python/rsyscall/tasks/connection.py:208-218`).
The server therefore MUST NOT read beyond the 56th byte of a request before executing it, MUST NOT
buffer stream data in user space across requests, and MUST NOT use `MSG_PEEK` or any other form of
look-ahead on `infd`; the only reads the server performs on `infd` are the request reads and the
`recvfrom` syscalls the client asks for (`python/rsyscall/tasks/connection.py:158-168`). This is
also what makes the activity-fd contract of §9 hold (`python/rsyscall/tasks/connection.py:101-108`).

**Execution.** The server MUST execute the request as the raw syscall `sys(args[0..5])` in its
own process, with the arguments exactly as received (§2), and MUST NOT filter, emulate or refuse
any syscall number: the client relies on `execve`, `execveat` and `exit` being executed literally
and on their connection hangup as the success signal (`python/rsyscall/unistd/exec.py:8-31`).

**Raw-syscall primitive.** Every syscall the server issues on the client's behalf MUST go through a
primitive whose instruction after `syscall` is `ret` and that does not touch the stack after the
syscall instruction, because a `clone` request with a new `child_stack` resumes the child at that
point with `rsp` pointing at the stack image, and the child must pop the trampoline address and
start executing it ("after executing the clone syscall, immediately call the ret instruction",
`python/rsyscall/sched.py:61-71`, `python/rsyscall/sched.py:139-151`, `python/rsyscall/handle/process.py:277-279`).
Consequently the child of a `clone` request never writes a response; only the parent does
(`python/rsyscall/tasks/clone.py:120`, `python/rsyscall/sched.py:151`). See `native-abi.md` §3.

**Response before next read.** After the syscall returns, the server MUST write the 8-byte
response (§4) before reading the next request: the client is entitled to wait for a response
before it sends anything else (`python/rsyscall/tasks/connection.py:135-147`,
`python/rsyscall/tasks/connection.py:228-242`), and the ordering guarantee of writes requires
that each request is complete before the next one starts (`python/rsyscall/near/sysif.py:101-111`).

**Strictly sequential.** Requests MUST be executed one at a time, in arrival order, and their
responses MUST be written in the same order; the client's `SyscallInterface` contract depends on
this sequencing (`python/rsyscall/near/sysif.py:105-108`,
`python/rsyscall/tasks/persistent.py:184-187`, `python/rsyscall/tasks/connection.py:228-259`).

**Blocking syscalls.** A blocking syscall such as `epoll_wait` or `waitid` blocks the whole loop;
that is intended, because the client registers the syscall socket itself on the epoll instance of
that process so that a blocked `epoll_wait` returns when more requests arrive
(`python/rsyscall/epoller.py:62-70`, `python/rsyscall/epoller.py:176-185`). The server MUST NOT
impose timeouts, retry or interrupt syscalls on its own: cancellation is the client's business and
is done with signals, whose `EINTR` result is simply returned (`python/rsyscall/near/sysif.py:81-86`).

Rationale: Observed (black-box): `strace -f -x -s 80 -o probe_stdin.strace -e trace=%network,%process,read,write,close,dup2,dup3,rt_sigprocmask,shutdown,unlink,unlinkat,openat,fcntl,exit,exit_group,futex,tkill,kill,prctl,readlink,readlinkat,chdir python3 probe_oracle.py reference/prefix/libexec/rsyscall stdin`
(driver described in `README.md` §4). The oracle reads each request with `read(fd, buf, 56)`,
and when a request was delivered in pieces of 10, 30 and 16 bytes it issued `read(fd, ..., 56) = 10`,
`read(fd, ..., 46) = 30`, `read(fd, ..., 16) = 16` before executing; with two requests already
queued it still read exactly 56 bytes at a time.

## 4. Response

A response is the raw kernel return value of the syscall as a native `long`: 8 bytes,
little-endian, two's complement (`python/rsyscall/tasks/connection.py:64-80`). The server MUST
write the value the kernel returned, unchanged: errors are negative errno values that the client
classifies itself (`-4095 < r < 0` raises `OSError(-r)`, `python/rsyscall/near/sysif.py:206-210`),
and the local backend feeds the raw value of `rsyscall_raw_syscall` to the same classifier
(`python/rsyscall/tasks/local.py:55-60`). The server MUST NOT translate to the libc `-1`/`errno`
convention, MUST NOT clamp or sign-adjust values, and MUST return `-EINTR` as is, because a signal
delivered to the server process is the client's cancellation mechanism
(`python/rsyscall/near/sysif.py:81-86`).

Examples (vectors `response_ok`, `response_enoent`):

```
0c 00 00 00 00 00 00 00   12   (e.g. write returned 12)
fe ff ff ff ff ff ff ff   -2   (ENOENT; the client raises OSError(2))
```

Rationale: because the client treats exactly -4095 as a success value (`python/rsyscall/near/sysif.py:208`),
the boundary is a client-side matter; the server has nothing to do about it. See `evolution-notes.md`.

## 5. Memory write (client to server)

The client writes into the server's memory by making the server receive the bytes itself. The
sequence on the wire is (`python/rsyscall/tasks/connection.py:158-168`):

| step | direction | bytes | meaning |
|---|---|---|---|
| 1 | client to server | 56 | request `recvfrom(server_fd, dest, len, MSG_WAITALL, 0, 0)` (`python/rsyscall/tasks/connection.py:159`, `python/rsyscall/sys/socket.py:592-600`, `python/rsyscall/sys/socket.py:679-681`) |
| 2 | client to server | `len` | the raw bytes to store at `dest`, sent as a `Write` request right after the syscall request (`python/rsyscall/tasks/connection.py:167-168`, `python/rsyscall/tasks/connection.py:208-218`) |
| 3 | server to client | 8 | the `recvfrom` result, which MUST be `len` on success (`python/rsyscall/tasks/connection.py:160-161`) |

Server obligations: having consumed exactly the 56 bytes of step 1 (§3), the server MUST execute
the `recvfrom` on the fd number given in `args[0]` (its own syscall socket) with the flags given
in `args[3]` (`MSG_WAITALL`), so that the kernel copies the next `len` stream bytes straight into
`dest` (`python/rsyscall/tasks/connection.py:158-161`). The server MUST NOT read those bytes as
requests and MUST NOT consume them in any other way (§3). A partial result breaks the connection
irrecoverably on the client side (`python/rsyscall/tasks/connection.py:160-161`), which is why §1
requires a blocking fd. The response of step 3 follows the rules of §3 and §4.

Example (vector `request_memory_write`, then 44 raw bytes, then the response `2c 00 00 00 00 00 00 00`):

```
2d 00 00 00 00 00 00 00   sys      = 45 (SYS_recvfrom)
0e 00 00 00 00 00 00 00   args[0]  = 14      (server_fd)
00 30 00 00 00 7f 00 00   args[1]  = 0x7f0000003000 (dest)
2c 00 00 00 00 00 00 00   args[2]  = 44      (len)
00 01 00 00 00 00 00 00   args[3]  = 0x100   (MSG_WAITALL)
00 00 00 00 00 00 00 00   args[4]  = 0
00 00 00 00 00 00 00 00   args[5]  = 0
<44 raw bytes>
```

Python-side behaviour: the memory write completes for the caller once the bytes have been sent
(`python/rsyscall/tasks/connection.py:217-218`); the `recvfrom` response is consumed by a
background coroutine (`python/rsyscall/tasks/connection.py:167`). The persistent variant waits
for that response before returning (`python/rsyscall/tasks/persistent.py:216-227`).

## 6. Memory read (server to client)

The client reads the server's memory by making the server send the bytes itself
(`python/rsyscall/tasks/connection.py:179-188`):

| step | direction | bytes | meaning |
|---|---|---|---|
| 1 | client to server | 56 | request `sendto(server_fd, src, len, MSG_NOSIGNAL, 0, 0)` (`python/rsyscall/tasks/connection.py:180`, `python/rsyscall/sys/socket.py:602-610`, `python/rsyscall/sys/socket.py:683-685`) |
| 2 | server to client | `len` | the memory contents, produced by the `sendto` itself (`python/rsyscall/tasks/connection.py:186-188`, `python/rsyscall/tasks/connection.py:243-253`) |
| 3 | server to client | 8 | the `sendto` result, which MUST be `len` on success (`python/rsyscall/tasks/connection.py:181-182`) |

The server MUST execute the `sendto` on the fd number given in `args[0]` (its own syscall socket)
so that the data enters the server-to-client stream, and MUST write the response only after the
syscall has returned, so that the stream carries the `len` data bytes followed by the 8-byte
result (`python/rsyscall/tasks/connection.py:186-188`). The client reserves its `Read(len)` slot
before it sends the request, which is why the data precedes the result in the response order
(`python/rsyscall/tasks/connection.py:186-187`, `python/rsyscall/tasks/connection.py:219-222`,
`python/dneio/concur.py:94-106`, `python/dneio/core.py:108-127`).

Example (vector `request_memory_read`; the stream then carries 44 data bytes and `2c 00 00 00 00 00 00 00`):

```
2c 00 00 00 00 00 00 00   sys      = 44 (SYS_sendto)
0e 00 00 00 00 00 00 00   args[0]  = 14      (server_fd)
00 30 00 00 00 7f 00 00   args[1]  = 0x7f0000003000 (src)
2c 00 00 00 00 00 00 00   args[2]  = 44      (len)
00 00 00 00 00 00 00 00   args[3]  = 0       (flags)
00 00 00 00 00 00 00 00   args[4]  = 0
00 00 00 00 00 00 00 00   args[5]  = 0
```

Rationale: a short `sendto` cannot be repaired by the server because the client has already
committed to reading `len` bytes (`python/rsyscall/tasks/connection.py:181-182`); on a blocking
Unix stream socket the kernel blocks until everything is queued, which is another reason for §1.

## 7. Barrier

A barrier puts nothing on the wire: it is a slot in the client's response queue that completes
once every earlier response has been consumed (`python/rsyscall/tasks/connection.py:190-191`,
`python/rsyscall/tasks/connection.py:254-257`). The persistent variant implements it as an
ordinary `getpid` request (`python/rsyscall/tasks/persistent.py:262-266`). No server behaviour
beyond §3 is required; in particular a server MUST NOT expect any barrier marker in the stream
(`python/rsyscall/tasks/connection.py:223-224`).

## 8. Ordering and pipelining

The client pipelines: its request coroutine sends request after request without waiting for
responses, and a separate coroutine consumes responses in order
(`python/rsyscall/tasks/connection.py:193-226`, `python/rsyscall/tasks/connection.py:228-259`).
The server MUST therefore preserve all of the following (`python/rsyscall/near/sysif.py:101-111`,
`python/rsyscall/tasks/connection.py:228-259`):

| guarantee | why the client needs it |
|---|---|
| requests are executed in arrival order, one at a time | writes are "guaranteed to be performed before any other operations" (`python/rsyscall/near/sysif.py:105-108`) |
| exactly one 8-byte response per request, in the same order | FIFO matching without ids (`python/rsyscall/tasks/connection.py:207`, `python/rsyscall/tasks/connection.py:236`) |
| memory-read data is immediately followed by its own response | the `Read` slot precedes the response slot (`python/rsyscall/tasks/connection.py:186-187`, `python/rsyscall/tasks/connection.py:247`) |
| a response is written as soon as its syscall returns | the caller may block on it before sending more (`python/rsyscall/tasks/connection.py:135-147`) |

The server MUST NOT coalesce, delay or batch responses waiting for further requests
(`python/rsyscall/tasks/connection.py:135-147`); it MAY write each response with a separate
`write`, since the client reads from a buffer that tolerates any fragmentation or coalescing of the
incoming stream (`python/rsyscall/epoller.py:719-742`).

Rationale: Observed (black-box): `strace -f -x -s 64 -e trace=read,recvfrom,write,sendto,sendmsg,recvmsg,clone,clone3,futex,kill,tgkill,tkill,exit,exit_group,shutdown -o hello.strace .venv/bin/python scripts/hello.py`
shows the client sending a long run of memory writes back to back and then reading 70 responses
(560 bytes) with a single `read`; the oracle wrote each response with one 8-byte `write`.

## 9. Activity fd contract

The client exposes `server_fd` as the "activity fd" of the process: "this fd is read by the
rsyscall server to receive syscalls, and when this fd is readable, it means there's syscalls to be
read" (`python/rsyscall/tasks/connection.py:101-108`, `python/rsyscall/near/sysif.py:134-145`).
In every process other than the local one, the client registers this fd, level-triggered, on that
process's epoll instance so that a blocked `epoll_wait` returns when requests are pending
(`python/rsyscall/epoller.py:62-70`, `python/rsyscall/epoller.py:176-185`). The server MUST keep
the invariant "`infd` readable if and only if unread requests exist": it MUST NOT hold request
bytes in user space (§3), and it MUST NOT read `infd` except to fetch the next request or to
execute a client-requested `recvfrom` (`python/rsyscall/tasks/connection.py:158-161`).

Python-side behaviour: the registration uses `EPOLL.IN|EPOLL.RDHUP|EPOLL.PRI|EPOLL.ERR|EPOLL.HUP`
(`python/rsyscall/epoller.py:180-184`), so a hangup of the syscall socket also wakes the
`epoll_wait`.

## 10. Termination

**Client side.** The client ends a connection with `shutdown(SHUT_RDWR)` on its access-side
socket; it never closes `server_fd` ("We don't close server_fd", `python/rsyscall/tasks/connection.py:110-117`).
It does so after the server process has exited or exec'd (`python/rsyscall/handle/__init__.py:268`,
`python/rsyscall/handle/__init__.py:293`, `python/rsyscall/handle/__init__.py:302`), when the
futex helper reports that the process is gone (`python/rsyscall/tasks/clone.py:129-138`), or when
the connection is already broken (`python/rsyscall/tasks/clone.py:132-136`).

**`exit` and `exec` produce no response.** The client sends `exit`, `execve` and `execveat` as
ordinary requests and treats the resulting hangup as success (`python/rsyscall/unistd/exec.py:8-31`,
`python/rsyscall/near/sysif.py:180-194`). The server MUST execute them literally (§3); a
successful `exit` ends the process and a successful `exec` replaces it, so no response is written
and the server MUST NOT attempt to emulate one before executing the syscall
(`python/rsyscall/unistd/exec.py:10-14`).

**Server side, plain server.** On end of file or a read error on `infd`, or on a write error on
`outfd`, the server MUST stop reading and writing on the connection: the client treats the
connection as permanently broken and never sends more (`python/rsyscall/near/sysif.py:166-178`,
`python/rsyscall/tasks/connection.py:110-117`), and `rsyscall_server` MUST return to its caller so
that the process can terminate as described in `native-abi.md` §3.5 (`python/ffibuilder.py:1237`,
`python/rsyscall/sched.py:61-71`). The exit status of the process is Unspecified in v0
(Recommended default: 0).

Rationale: nothing in `python/` can observe what a plain server does after EOF; a lingering
server would only pin the parent's address space and fds. Observed (black-box):
`bash -c 'source scripts/env.sh && strace -f -x -s 80 -o probe_persistent3.strace -e trace=%network,clone,clone3,read,write,close,exit,exit_group,futex,tkill,kill,unshare,unlink,unlinkat "$PY" -u probe_persistent3.py'`
(driver described in `README.md` §4): after the client's `shutdown(SHUT_RDWR)` the cloned server
did `read(14, "", 56) = 0` and then `exit(0)`, and the client saw
`ChildState(code=CLD.EXITED, exit_status=0)`.

**Server side, persistent server (`SHUT_WR` case).** To reconnect, the client shuts down only the
write side of its current connection; "any currently running or pending syscalls (such as
epoll_wait) will be able to finish and receive their response, after which the syscall server will
close its end of the current connection and start listening for a new connection"
(`python/rsyscall/tasks/persistent.py:140-148`). The persistent server therefore MUST finish the
request in progress, MUST write its response (the client's read side is still open), MUST then
treat the EOF on `infd` as the end of the connection, MUST NOT exit, and MUST proceed to accept a
new connection as specified in `bootstrap-handshakes.md` §5
(`python/rsyscall/tasks/persistent.py:141-144`, `python/rsyscall/tasks/persistent.py:377-405`).

**SIGPIPE.** A persistent process exists to survive the death of the client ("We may crash, but
the process and all its children will stay alive", `python/rsyscall/tasks/persistent.py:16-22`);
when the client dies between a request and its response, the server's write of the response hits
a closed peer. The persistent server MUST NOT be killed by `SIGPIPE` in that situation and MUST
NOT rely on an inherited signal disposition for this (for example it can send with `MSG_NOSIGNAL`),
because it may be cloned from a process with default dispositions
(`python/rsyscall/tasks/persistent.py:16-22`, `python/rsyscall/tasks/persistent.py:141-148`,
`python/rsyscall/tasks/ssh.py:303`). The plain server SHOULD behave the same way
(`python/rsyscall/tasks/clone.py:132-136`).

Rationale: the client itself sends with `MSG_NOSIGNAL` for the symmetric reason
(`python/rsyscall/tasks/connection.py:200`, `python/rsyscall/tasks/connection.py:211`).

## 11. Python-side behaviour

Python-side behaviour: a failure to send a request raises `SyscallSendError`, which guarantees
that the request was not executed (`python/rsyscall/tasks/connection.py:201-204`,
`python/rsyscall/tasks/connection.py:212-215`, `python/rsyscall/near/sysif.py:196-204`); any
failure while reading a response or memory-read data raises `SyscallHangup`, which leaves the
outcome of that request unknown (`python/rsyscall/tasks/connection.py:237-240`,
`python/rsyscall/tasks/connection.py:248-251`, `python/rsyscall/near/sysif.py:180-194`); both are
permanent for that connection (`python/rsyscall/near/sysif.py:166-178`).

Python-side behaviour: for exit and exec the hangup is swallowed as success
(`python/rsyscall/unistd/exec.py:8-31`); a hangup during `close` puts the fd back for another task
to close (`python/rsyscall/handle/fd.py:234-247`).

Python-side behaviour: the persistent client retries a request that failed with
`SyscallSendError` on the next connection, blocks all requests while disconnected, and retries a
memory read on `BrokenPipeError` (`python/rsyscall/tasks/persistent.py:10-14`,
`python/rsyscall/tasks/persistent.py:198-260`); it never retries after `SyscallHangup`
(`python/rsyscall/tasks/persistent.py:12-14`). The process-local `epoll_wait` loop retries once
after a `SyscallHangup` to support reconnection (`python/rsyscall/epoller.py:186-192`).

Python-side behaviour: the class docstring speaks of batching requests
(`python/rsyscall/tasks/connection.py:7-9`), but each request is sent with its own `send_all`
(`python/rsyscall/tasks/connection.py:200`, `python/rsyscall/tasks/connection.py:211`); the
kernel may still coalesce them, which §3 already requires the server to handle.

## 12. Conformance vectors

`vectors/v0.json` (generated by `scripts/spec-vectors.py`, checked by `make spec-check`) contains
the byte-exact images referenced above: `request_write`, `request_negative_arg`,
`request_memory_write`, `request_memory_read`, `response_ok` and `response_enoent`. Each vector
records the `python/` lines it is derived from and the `struct.pack` expression that generates it;
the default mode of the script rebuilds every vector with the client's own classes
(`RsyscallSyscall`, `SyscallResponse`) and fails if a single byte differs
(`python/rsyscall/tasks/connection.py:32-50`, `python/rsyscall/tasks/connection.py:64-80`).
