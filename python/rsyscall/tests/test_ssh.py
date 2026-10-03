from __future__ import annotations

from rsyscall import AsyncChildPid, Process
from rsyscall.tests.trio_test_case import TrioTestCase
import rsyscall.thread
from rsyscall.nix import enter_nix_container, deploy
import importlib.util
import unittest
from rsyscall.tasks.ssh import *

from rsyscall.unistd import SEEK
from rsyscall.signal import Sigset, HowSIG
from rsyscall.sys.mman import MFD
from rsyscall.sched import CLONE

from rsyscall.handle import FileDescriptor
from rsyscall.thread import Process, Command
from rsyscall.command import Command
from rsyscall.monitor import AsyncChildPid
from rsyscall.stdlib import mkdtemp
import rsyscall.tasks.ssh as ssh_module
from rsyscall.path import Path
from rsyscall.sys.socket import AF, SOCK
from rsyscall.sys.stat import Stat
from rsyscall.sys.un import SockaddrUn
from rsyscall.sys.wait import W
import os
import signal
import stat
import trio
import typing as t
import unittest.mock

# import logging
# logging.basicConfig(level=logging.DEBUG)

async def start_cat(process: Process, cat: Command,
                    stdin: FileDescriptor, stdout: FileDescriptor) -> AsyncChildPid:
    process = await process.fork()
    await process.task.inherit_fd(stdin).dup2(process.stdin)
    await process.task.inherit_fd(stdout).dup2(process.stdout)
    child = await process.exec(cat)
    return child

async def wait_until_gone(path: str, timeout: float = 30) -> None:
    "Wait until nothing exists at path; fail after timeout seconds"
    with trio.fail_after(timeout):
        while os.path.lexists(path):
            await trio.sleep(0.2)

def unique_name() -> str:
    "A socket name no other test run uses, since the janitor's name mode matches any directory"
    return f"host{os.urandom(6).hex()}.sock"

def processes_with_argument(argument: str) -> t.Dict[int, int]:
    "The processes with argument among their arguments, as a dict from pid to parent pid"
    found = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as f:
                arguments = f.read().split(b"\0")
            with open(f"/proc/{entry}/stat") as f:
                fields = f.read().rsplit(")", 1)[1].split()
        except OSError:
            continue
        if os.fsencode(argument) in arguments:
            found[int(entry)] = int(fields[1])
    return found

class TestSSH(TrioTestCase):
    host: SSHHost
    local_child: AsyncChildPid
    remote: Process

    @classmethod
    async def asyncSetUpClass(cls) -> None:
        cls.host = await make_local_ssh(cls.process)
        cls.local_child, cls.remote = await cls.host.ssh(cls.process)

    @classmethod
    async def asyncTearDownClass(cls) -> None:
        await cls.local_child.kill()

    async def test_read(self) -> None:
        [(local_sock, remote_sock)] = await self.remote.open_channels(1)
        data = b"hello world"
        await local_sock.write(await self.process.task.ptr(data))
        valid, _ = await remote_sock.read(await self.remote.task.malloc(bytes, len(data)))
        self.assertEqual(len(data), valid.size())
        self.assertEqual(data, await valid.read())

    async def test_connection_multiple_channels(self) -> None:
        """Test that using open_channels(n) for n > 1 produces working channels.

        Our parallelization for this function was previously buggy and broke the channels.
        """
        [
            (local_sock, remote_sock),
            *rest,
        ] = await self.remote.open_channels(10)
        data = b'foobar'
        _, remaining = await local_sock.write(await self.process.ptr(data))
        self.assertEqual(remaining.size(), 0, msg="Got partial write")
        read_data, _ = await remote_sock.read(await self.remote.malloc(bytes, len(data)))
        self.assertEqual(data, await read_data.read())

    async def test_exec_true(self) -> None:
        true = await self.process.environ.which('true')
        await self.remote.run(true)

    async def test_exec_pipe(self) -> None:
        [(local_sock, remote_sock)] = await self.remote.open_channels(1)
        cat = await self.process.environ.which('cat')
        process = await self.remote.fork()
        cat_side = process.task.inherit_fd(remote_sock)
        await remote_sock.close()
        await cat_side.dup2(process.stdin)
        await cat_side.dup2(process.stdout)
        child_pid = await process.exec(cat)

        in_data = await self.process.task.ptr(b"hello")
        written, _ = await local_sock.write(in_data)
        valid, _ = await local_sock.read(written)
        self.assertEqual(in_data.value, await valid.read())

    async def test_clone(self) -> None:
        process1 = await self.remote.fork()
        process2 = await process1.fork()
        await process2.exit(0)
        await process1.exit(0)

    async def test_nest(self) -> None:
        local_child, remote = await self.host.ssh(self.remote)
        await local_child.kill()

    async def test_copy(self) -> None:
        cat = await self.process.environ.which('cat')

        local_file = await self.process.task.memfd_create(await self.process.ptr("source"))
        remote_file = await self.remote.task.memfd_create(await self.remote.ptr("dest"))

        data = b'hello world'
        await local_file.write(await self.process.task.ptr(data))
        await local_file.lseek(0, SEEK.SET)

        [(local_sock, remote_sock)] = await self.remote.open_channels(1)

        local_child = await start_cat(self.process, cat, local_file, local_sock)
        await local_sock.close()

        remote_child = await start_cat(self.remote, cat, remote_sock, remote_file)
        await remote_sock.close()

        await local_child.check()
        await remote_child.check()

        await remote_file.lseek(0, SEEK.SET)
        read, _ = await remote_file.read(await self.remote.task.malloc(bytes, len(data)))
        self.assertEqual(await read.read(), data)

    async def test_sigmask_bug(self) -> None:
        process = await self.remote.fork()
        await rsyscall.thread.do_cloexec_except(
            process, set([fd.near for fd in process.task.fd_handles]))
        await self.remote.task.sigprocmask((HowSIG.SETMASK,
                                            await self.remote.task.ptr(Sigset())),
                                           await self.remote.task.malloc(Sigset))
        await self.remote.task.read_oldset_and_check()

    @unittest.skipIf(importlib.util.find_spec("rsyscall._nixdeps") is None, "needs a Nix store (rsyscall._nixdeps)")
    async def test_nix_deploy(self) -> None:
        import rsyscall._nixdeps.nix, rsyscall._nixdeps.coreutils
        # make it locally so that it can be cleaned up even when the
        # remote enters the container
        tmpdir = await mkdtemp(self.process)
        async with tmpdir:
            await enter_nix_container(self.process, rsyscall._nixdeps.nix.closure, self.remote, tmpdir)
            true = (await deploy(self.remote, rsyscall._nixdeps.coreutils.closure)).bin('true')
            await self.remote.run(true)

    async def ssh_with_quick_janitors(self) -> t.Tuple[AsyncChildPid, Process, str]:
        "ssh to the host with janitors that check every second; also return the bootstrap directory"
        with unittest.mock.patch.object(ssh_module, "_JANITOR_MAX_INTERVAL", 1):
            with self.assertLogs("rsyscall.tasks.ssh", "DEBUG") as logs:
                local_child, remote = await self.host.ssh(self.process)
        [tmp_dir] = [os.fsdecode(record.args[0]) for record in logs.records
                     if record.msg == "socket bootstrap done, got tmp path %s"]
        return local_child, remote, tmp_dir

    async def test_temp_files_reclaimed(self) -> None:
        "The bootstrap executable goes at once, the rest of its directory once nothing uses it"
        local_child, remote, tmp_dir = await self.ssh_with_quick_janitors()
        self.assertFalse(os.path.lexists(os.path.join(tmp_dir, "bootstrap")))
        self.assertTrue(stat.S_ISSOCK(os.lstat(os.path.join(tmp_dir, "data")).st_mode))
        # the remote process still starts in the temporary directory
        pid = (await remote.task.getpid()).id
        self.assertEqual(os.readlink(f"/proc/{pid}/cwd"), tmp_dir)
        await remote.exit(0)
        await local_child.waitpid(W.EXITED)
        await wait_until_gone(tmp_dir)

    async def test_local_socket_reclaimed(self) -> None:
        "The socket of the forwarding ssh goes once that ssh has exited"
        local_child, remote, tmp_dir = await self.ssh_with_quick_janitors()
        name = os.path.basename(os.fsdecode(remote.connection.access_address.value.path))
        sock_path = os.path.join(os.fsdecode(self.process.environ.tmpdir), name)
        self.assertTrue(stat.S_ISSOCK(os.lstat(sock_path).st_mode))
        await remote.exit(0)
        await local_child.waitpid(W.EXITED)
        # The forwarding ssh outlives the session by up to a minute (its "sleep 60"); end it now.
        [forward] = processes_with_argument(f"./{name}:{tmp_dir}/data")
        os.kill(forward, signal.SIGTERM)
        await wait_until_gone(sock_path)

    async def test_forwarder_reaped(self) -> None:
        "The forwarding ssh does not stay a zombie once it has exited"
        local_child, remote, tmp_dir = await self.ssh_with_quick_janitors()
        name = os.path.basename(os.fsdecode(remote.connection.access_address.value.path))
        [forward] = processes_with_argument(f"./{name}:{tmp_dir}/data")
        await remote.exit(0)
        await local_child.waitpid(W.EXITED)
        os.kill(forward, signal.SIGTERM)
        await wait_until_gone(f"/proc/{forward}", timeout=10)

class TestSSHJanitor(TrioTestCase):
    "The janitor of rsyscall.tasks.ssh, on sockets made here, checking every second"
    async def asyncSetUp(self) -> None:
        self.tmpdir = await mkdtemp(self.process, "test_janitor")
        self.base = os.fsdecode(self.tmpdir)

    async def asyncTearDown(self) -> None:
        await self.tmpdir.cleanup()

    def directory(self, name: str) -> str:
        path = os.path.join(self.base, name)
        os.mkdir(path)
        return path

    async def listen(self, path: str) -> FileDescriptor:
        sock = await self.process.task.socket(AF.UNIX, SOCK.STREAM)
        await sock.bind(await self.process.ptr(await SockaddrUn.from_path(self.process, path)))
        await sock.listen(1)
        return sock

    async def inode(self, sock: FileDescriptor) -> str:
        return str((await (await sock.fstat(await self.process.task.malloc(Stat))).read()).ino)

    async def janitor(self, mode: str, key: str, files: t.List[str], directory: str = "") -> bool:
        return await ssh_module._start_janitor(self.process, mode, key, files, directory, max_interval=1)

    async def test_inode(self) -> None:
        d = self.directory("d")
        sock = await self.listen(os.path.join(d, "data"))
        open(os.path.join(d, "bootstrap"), "w").close()
        files = [os.path.join(d, "data"), os.path.join(d, "bootstrap")]
        self.assertTrue(await self.janitor("inode", await self.inode(sock), files, d))
        await trio.sleep(3)
        self.assertTrue(os.path.lexists(os.path.join(d, "data")))
        await sock.close()
        await wait_until_gone(d)

    async def test_name(self) -> None:
        name = unique_name()
        path = os.path.join(self.base, name)
        sock = await self.listen(path)
        self.assertTrue(await self.janitor("name", name, [path]))
        await trio.sleep(2)
        self.assertTrue(os.path.lexists(path))
        await sock.close()
        await wait_until_gone(path)

    async def test_not_listed(self) -> None:
        path = os.path.join(self.base, "file")
        open(path, "w").close()
        self.assertFalse(await self.janitor("name", unique_name(), [path]))
        await trio.sleep(2)
        self.assertTrue(os.path.exists(path))

    async def test_keeps_other_files(self) -> None:
        d = self.directory("d")
        sock = await self.listen(os.path.join(d, "data"))
        open(os.path.join(d, "user.txt"), "w").close()
        self.assertTrue(await self.janitor("inode", await self.inode(sock), [os.path.join(d, "data")], d))
        await sock.close()
        await wait_until_gone(os.path.join(d, "data"))
        await trio.sleep(3)
        self.assertTrue(os.path.exists(os.path.join(d, "user.txt")))

    async def test_waits_for_cwd(self) -> None:
        d = self.directory("d")
        # forked before the socket exists, so that it does not hold the listener
        holder = await self.process.fork()
        await holder.task.chdir(await holder.ptr(Path(d)))
        sock = await self.listen(os.path.join(d, "data"))
        self.assertTrue(await self.janitor("inode", await self.inode(sock), [os.path.join(d, "data")], d))
        await sock.close()
        await wait_until_gone(os.path.join(d, "data"))
        await trio.sleep(3)
        self.assertTrue(os.path.isdir(d))
        await holder.exit(0)
        await wait_until_gone(d)

    async def test_detached(self) -> None:
        "The janitor has a session of its own, / as its cwd, /dev/null as its stdio, no other file"
        pipe = await self.process.pipe()
        await pipe.write.disable_cloexec()
        name = unique_name()
        path = os.path.join(self.base, name)
        sock = await self.listen(path)
        self.assertTrue(await self.janitor("name", name, [path]))
        await pipe.write.close()
        reader = await self.process.make_afd(pipe.read, set_nonblock=True)
        with trio.fail_after(10):
            self.assertEqual(await reader.read_some_bytes(), b"")
        janitors = processes_with_argument(name)
        [pid] = [pid for pid, parent in janitors.items() if parent not in janitors]
        with open(f"/proc/{pid}/stat") as f:
            session = int(f.read().rsplit(")", 1)[1].split()[3])
        self.assertNotEqual(session, os.getsid(0))
        self.assertEqual(os.readlink(f"/proc/{pid}/cwd"), "/")
        for fd in range(3):
            self.assertEqual(os.readlink(f"/proc/{pid}/fd/{fd}"), "/dev/null")
        await sock.close()
        await wait_until_gone(path)
