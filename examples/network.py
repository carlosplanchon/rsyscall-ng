"""Isolate a process's network with a network namespace.

A child is cloned into new user and network namespaces. Its namespace starts with only a
loopback interface, and that interface is down, so the child brings it up with an ioctl. From
inside, the host's network is out of reach: a server this script runs on the host's 127.0.0.1
refuses the connection, because the child's 127.0.0.1 is a different interface, and no other
address has a route. Then the child and a process it forks talk to each other over their
private loopback.

Usage:  python3 network.py

Needs unprivileged user namespaces. On Ubuntu 24.04 AppArmor restricts them; see the
kernel.apparmor_restrict_unprivileged_userns sysctl.
"""
import errno
import sys

import trio

from rsyscall import local_process
from rsyscall.net.if_ import IFF, SIOC, Ifreq
from rsyscall.netinet.in_ import SockaddrIn
from rsyscall.sched import CLONE
from rsyscall.sys.socket import AF, SOCK

SKIP = 77  # exit status for "a prerequisite is missing"

async def main() -> int:
    # A server on the host's loopback. The interpreter's own process must never block, so its
    # sockets are non-blocking and wrapped for async use (make_afd).
    host_server = await local_process.make_afd(
        await local_process.socket(AF.INET, SOCK.STREAM|SOCK.NONBLOCK))
    host_addr = await local_process.bind_getsockname(host_server.handle, SockaddrIn(0, "127.0.0.1"))
    await host_server.handle.listen(1)
    print("host server listening on", host_addr)

    try:
        ns = await local_process.clone(CLONE.NEWUSER|CLONE.NEWNET)
    except PermissionError:
        print("unprivileged user namespaces are not available here", file=sys.stderr)
        return SKIP
    try:
        # The child holds every capability in its new user namespace, which owns the new
        # network namespace, so it may configure the interfaces there.
        ctl = await ns.task.socket(AF.INET, SOCK.STREAM)
        await ctl.ioctl(SIOC.SIFFLAGS, await ns.ptr(Ifreq("lo", flags=IFF.UP)))

        # Blocking calls are fine in the child: only the child's process waits.
        probe = await ns.task.socket(AF.INET, SOCK.STREAM)
        try:
            await probe.connect(await ns.ptr(host_addr))
            print("unexpected: the host server was reachable")
            return 1
        except ConnectionRefusedError:
            print("inside: the host's server is out of reach (connection refused)")
        probe = await ns.task.socket(AF.INET, SOCK.STREAM)
        try:
            await probe.connect(await ns.ptr(SockaddrIn(80, "192.0.2.1")))
            print("unexpected: an outside address was reachable")
            return 1
        except OSError as err:
            if err.errno != errno.ENETUNREACH:
                raise
            print("inside: no route to anywhere else (network unreachable)")

        # A server in the namespace, and a client in a process forked from it, which shares
        # the namespace. connect() completes against the listen backlog, so the sequence of
        # calls below never waits on itself.
        server = await ns.task.socket(AF.INET, SOCK.STREAM)
        addr = await ns.bind_getsockname(server, SockaddrIn(0, "127.0.0.1"))
        await server.listen(1)
        client_process = await ns.fork()
        try:
            client = await client_process.task.socket(AF.INET, SOCK.STREAM)
            await client.connect(await client_process.ptr(addr))
            await client.write(await client_process.ptr(b"ping"))
            conn = await server.accept()
            request, _ = await conn.read(await ns.malloc(bytes, 64))
            await conn.write(await ns.ptr(b"pong to " + await request.read()))
            reply, _ = await client.read(await client_process.malloc(bytes, 64))
            print("inside: the client got", repr(await reply.read()), "over the private loopback")
        finally:
            await client_process.exit(0)
    finally:
        await ns.exit(0)
        await host_server.close()
    return 0

if __name__ == "__main__":
    sys.exit(trio.run(main))
