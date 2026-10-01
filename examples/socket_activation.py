"""Start a server on a socket it inherits, the way systemd's socket activation does.

This script creates the listening socket itself, forks a child, places the socket at file
descriptor 3 in the child, sets LISTEN_FDS and LISTEN_PID as the socket activation protocol
describes, and execs a server that never opens a socket of its own: it serves on fd 3. Clients
can connect as soon as the socket listens, even before the server has started, because the
kernel queues their connections in the listen backlog.

The server here is a few lines of plain Python; any program that understands LISTEN_FDS works
the same way.

Usage:  python3 socket_activation.py
"""
import sys

import trio

from rsyscall import Command, local_process
from rsyscall.near.types import FileDescriptor
from rsyscall.netinet.in_ import SockaddrIn
from rsyscall.path import Path
from rsyscall.sys.socket import AF, SOCK

SERVER = """
import os, socket
assert os.environ["LISTEN_FDS"] == "1" and int(os.environ["LISTEN_PID"]) == os.getpid()
listener = socket.socket(fileno=3)  # family and type are detected from the inherited socket
conn, _ = listener.accept()
conn.sendall(b"pid %d served %r on a socket it inherited" % (os.getpid(), conn.recv(64)))
conn.close()
"""

async def main() -> int:
    listener = await local_process.socket(AF.INET, SOCK.STREAM)
    addr = await local_process.bind_getsockname(listener, SockaddrIn(0, "127.0.0.1"))
    await listener.listen(16)
    print("listening on", addr)

    # The child inherits a copy of our file descriptor table, so the socket must exist before
    # the fork. Every descriptor rsyscall creates is close-on-exec; dup2 makes a copy at fd 3
    # that is not, so it is the one that survives the exec.
    child = await local_process.fork()
    inherited = child.task.inherit_fd(listener)
    await inherited.dup2(child.task.make_fd_handle(FileDescriptor(3)))
    server = await child.exec(
        Command(Path(sys.executable), [sys.executable, "-c", SERVER], {})
        .env(LISTEN_FDS="1", LISTEN_PID=str(child.task.pid.near.id)))
    await listener.close()  # the server holds the socket now

    # A client in this process: non-blocking, so the interpreter never stalls on it.
    client = await local_process.make_afd(
        await local_process.socket(AF.INET, SOCK.STREAM|SOCK.NONBLOCK))
    await client.connect(await local_process.ptr(addr))
    await client.write_all_bytes(b"ping")
    print("client got:", (await client.read_some_bytes()).decode())
    await client.close()
    await server.check()
    return 0

if __name__ == "__main__":
    sys.exit(trio.run(main))
