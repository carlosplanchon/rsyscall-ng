"""Black-box probe: what does the oracle server do when the client hangs up the syscall socket?"""
import trio, rsyscall
from rsyscall.sys.wait import W

async def main() -> None:
    t = await rsyscall.local_process.fork()
    print("child pid:", t.task.pid.near.id)
    await t.task.sysif.close_interface()          # client side: shutdown(SHUT_RDWR)
    state = await t.pid.waitpid(W.EXITED)
    print("child state after client hangup:", state)

trio.run(main)
