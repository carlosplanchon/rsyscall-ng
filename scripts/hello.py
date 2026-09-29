"""Smoke test for the native backend.

Clone a child process sharing our address space (an rsyscall server runs inside it
via the native trampoline), write to the child's stdout through a remote pointer,
exec `echo` in it and wait for the exit status.
"""
import trio
import rsyscall

async def main() -> None:
    t = await rsyscall.local_process.fork()
    print("child task:", t.task.pid, "sysif:", t.task.sysif)
    await t.stdout.write(await t.ptr(b"Hello world from a cloned rsyscall process!\n"))
    echo = await t.environ.which("echo")
    child = await t.exec(echo.args("hello from exec, via rsyscall"))
    print("exec'd child exited:", await child.check())

trio.run(main)
