import os
import tempfile

from rsyscall.environ import ExecutableNotFound
from rsyscall.tests.trio_test_case import TrioTestCase

def make_executable(directory: str, name: str) -> str:
    path = os.path.join(directory, name)
    with open(path, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(path, 0o755)
    return path

class TestEnviron(TrioTestCase):
    async def test_which_takes_a_name_with_a_slash_as_a_path(self) -> None:
        "Like execvp: such a name is not looked up on PATH"
        with tempfile.TemporaryDirectory() as tmp:
            os.mkdir(os.path.join(tmp, "sub"))
            make_executable(os.path.join(tmp, "sub"), "tool")
            child = await self.process.fork()
            await child.task.chdir(await child.ptr(tmp))
            cmd = await child.environ.which("sub/tool")
            self.assertEqual(os.fspath(cmd.executable_path), "sub/tool")
            with self.assertRaises(ExecutableNotFound):
                await child.environ.which("sub/missing")
            await (await child.exec(cmd)).check()

    async def test_assigning_path_updates_which(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool = make_executable(tmp, "rsyscall-test-tool")
            child = await self.process.fork()
            with self.assertRaises(ExecutableNotFound):
                await child.environ.which("rsyscall-test-tool")
            child.environ["PATH"] = tmp
            cmd = await child.environ.which("rsyscall-test-tool")
            self.assertEqual(os.fspath(cmd.executable_path), tool)
            await (await child.exec(cmd)).check()

    async def test_changes_after_the_envp_was_built(self) -> None:
        "The envp array is cached; changing a variable used to leave it stale"
        child = await self.process.fork()
        await child.environ.as_arglist(child.task)
        child.environ["RSYSCALL_TEST_VAR"] = "late"
        await (await child.exec(child.environ.sh.args('-c', 'test "$RSYSCALL_TEST_VAR" = late'))).check()
        child = await self.process.fork()
        await child.environ.as_arglist(child.task)
        child.environ.data = {"ONLY": "1"}
        await (await child.exec(child.environ.sh.args('-c', 'test "$ONLY" = 1 && test -z "$HOME"'))).check()
