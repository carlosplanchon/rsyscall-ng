import signal

from rsyscall.command import Command
from rsyscall.fcntl import O
from rsyscall.handle import ChildDeadError
from rsyscall.path import Path
from rsyscall.signal import SIG
from rsyscall.sys.wait import CLD, W
from rsyscall.tests.trio_test_case import TrioTestCase

class TestChild(TrioTestCase):
    async def test_killed_by_realtime_signal(self) -> None:
        "SIG only names the standard signals; the state of such a child used to be lost"
        number = int(signal.SIGRTMIN) + 2
        child = await self.process.fork()
        child_pid = await child.exec(child.environ.sh.args('-c', f'kill -{number} $$'))
        state = await child_pid.waitpid(W.EXITED)
        self.assertIs(state.code, CLD.KILLED)
        self.assertEqual(state.killed_with(), number)
        self.assertIs(child_pid.pid.death_state, state)

    async def test_failed_exec_leaves_the_child_usable(self) -> None:
        "A failed execve used to leave the fd table marked as being manipulated"
        child = await self.process.fork()
        with self.assertRaises(FileNotFoundError):
            await child.exec(Command(Path("/nonexistent/program"), ["program"], {}))
        await child.task.open(await child.ptr("/dev/null"), O.RDONLY)
        await (await child.exec(child.environ.sh.args('-c', 'true'))).check()

    async def test_signalling_a_reaped_child(self) -> None:
        child = await self.process.fork()
        child_pid = await child.exec(child.environ.sh.args('-c', 'true'))
        await child_pid.check()
        with self.assertRaises(ChildDeadError):
            await child_pid.kill(SIG.TERM)
