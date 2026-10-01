"""Reconnect to a process after its connection is gone.

A persistent process listens on a Unix socket for new connections, so it outlives the one it was
created with. This script creates one, makes it persistent (its own session, and no signal when
this script dies), and gives it some state: a pipe holding a message. Then it drops the
connection and connects again through the socket. The same process answers, with its state
intact.

Reconnecting from another interpreter is not supported yet: reconnect() needs the Python objects
of the script that created the process.

Usage:  python3 persistent.py
"""
import sys

import trio

from rsyscall import local_process
from rsyscall.stdlib import mkdtemp
from rsyscall.tasks.persistent import clone_persistent

async def main() -> int:
    async with (await mkdtemp(local_process, "persistent")) as tmpdir:
        process = await clone_persistent(local_process, tmpdir/"persist.sock")
        try:
            await process.make_persistent()
            pid = await process.task.getpid()
            pipe = await process.pipe()  # state that lives in the persistent process
            await pipe.write.write(await process.ptr(b"written before the reconnection"))
            print("persistent process", pid.id, "holds a pipe with a message in it")

            # Shut the current connection down and open a new one through the socket.
            await process.reconnect(local_process)

            print("after reconnecting, the process is", (await process.task.getpid()).id)
            message, _ = await pipe.read.read(await process.malloc(bytes, 64))
            print("and its pipe still holds:", (await message.read()).decode())
        finally:
            await process.exit(0)  # a persistent process would otherwise outlive this script
    return 0

if __name__ == "__main__":
    sys.exit(trio.run(main))
