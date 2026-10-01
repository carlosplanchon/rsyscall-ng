from __future__ import annotations

from rsyscall.tests.trio_test_case import TrioTestCase
from rsyscall import FileDescriptor, Pointer
from rsyscall.epoller import *
import trio
import outcome

from rsyscall.tests.utils import do_async_things
from rsyscall.near.sysif import SyscallInterface, Syscall, SyscallHangup
from rsyscall.sys.syscall import SYS
from rsyscall.sys.epoll import EPOLL_CTL
from rsyscall.fcntl import O
from dneio import RequestQueue, reset, Continuation
import typing as t

class DelayResultSysif(SyscallInterface):
    def __init__(self, sysif: SyscallInterface,
                 delay_queue: RequestQueue[t.Tuple[Syscall, outcome.Outcome[int]], None]) -> None:
        self.sysif = sysif
        self.delay_queue = delay_queue

    async def syscall(self, number: SYS, arg1=0, arg2=0, arg3=0, arg4=0, arg5=0, arg6=0) -> int:
        syscall = Syscall(number, arg1, arg2, arg3, arg4, arg5, arg6)
        ret = await outcome.acapture(self.sysif.syscall, number, arg1, arg2, arg3, arg4, arg5, arg6)
        await self.delay_queue.request((syscall, ret))
        return ret.unwrap()

    async def close_interface(self) -> None:
        return await self.sysif.close_interface()

    def get_activity_fd(self) -> t.Optional[FileDescriptor]:
        return self.sysif.get_activity_fd()

class TestEpoller(TrioTestCase):
    async def test_local(self) -> None:
        await do_async_things(self, self.process.epoller, self.process)

    async def test_multi(self) -> None:
        await do_async_things(self, self.process.epoller, self.process, 0)
        async with trio.open_nursery() as nursery:
            for i in range(1, 6):
                nursery.start_soon(do_async_things, self, self.process.epoller, self.process, i)

    async def test_process_multi(self) -> None:
        process = await self.process.fork()
        await do_async_things(self, process.epoller, process, 0)
        async with trio.open_nursery() as nursery:
            for i in range(1, 6):
                nursery.start_soon(do_async_things, self, process.epoller, process, i)

    async def test_process_root_epoller(self) -> None:
        process = await self.process.fork()
        epoller = await Epoller.make_root(process.task)
        await do_async_things(self, epoller, process)

    async def test_afd_with_handle(self):
        pipe = await self.process.pipe()
        afd = await self.process.make_afd(pipe.write, set_nonblock=True)
        new_afd = afd.with_handle(pipe.write)
        await new_afd.write_all_bytes(b'foo')

    async def test_delayed_eagain(self):
        pipe = await self.process.pipe()
        process = await self.process.fork()
        async_pipe_rfd = await process.make_afd(process.inherit_fd(pipe.read), set_nonblock=True)
        # write in parent, read in child
        input_data = b'hello'
        buf_to_write: Pointer[bytes] = await self.process.ptr(input_data)
        buf_to_write, _ = await pipe.write.write(buf_to_write)
        self.assertEqual(await async_pipe_rfd.read_some_bytes(), input_data)
        buf = await process.malloc(bytes, 4096)
        # set up the EAGAIN to be delayed
        queue: RequestQueue[t.Tuple[Syscall, outcome.Outcome[int]], None] = RequestQueue()
        old_sysif = process.task.sysif
        process.task.sysif = DelayResultSysif(old_sysif, queue)
        @self.nursery.start_soon
        async def race_eagain():
            # wait for EAGAIN
            (syscall, result), cb = await queue.get_one()
            self.assertIsInstance(result.error, BlockingIOError)
            process.task.sysif = old_sysif
            queue.close(Exception("remaining syscalls?"))
            # write data after the EAGAIN
            await pipe.write.write(buf_to_write)
            # give epoll event a chance to be read - it will be available immediately
            await trio.sleep(0)
            # resume the suspended EAGAIN coroutine, which should keep running and get data
            cb.send(None)
        valid, remaining = await async_pipe_rfd.read(buf)

    async def test_wrong_op_on_pipe(self):
        "Reading or writing to the wrong side of a pipe fails immediately with an error"
        pipe = await self.process.pipe()
        async_pipe_wfd = await self.process.make_afd(pipe.write, set_nonblock=True)
        async_pipe_rfd = await self.process.make_afd(pipe.read, set_nonblock=True)
        # we actually are defined to get EBADF in this case, which is
        # a bit of a worrying error, but whatever
        with self.assertRaises(OSError) as cm:
            await async_pipe_wfd.read_some_bytes()
        self.assertEqual(cm.exception.errno, 9)
        with self.assertRaises(OSError) as cm:
            await async_pipe_rfd.write_all_bytes(b'hi')
        self.assertEqual(cm.exception.errno, 9)

class SwitchableActivityFdSysif(SyscallInterface):
    """Forward to `sysif`, but report `activity_fd` as the activity fd, which tests can change.

    Setting `lose` to an `(op, fd)` pair makes the next epoll_ctl with that op on that fd lose
    its response: the call is performed, then raises SyscallHangup, as if the connection broke
    before the response arrived.

    """
    def __init__(self, sysif: SyscallInterface) -> None:
        self.sysif = sysif
        self.activity_fd = sysif.get_activity_fd()
        self.lose: t.Optional[t.Tuple[EPOLL_CTL, FileDescriptor]] = None
        self.lost: t.List[Syscall] = []

    async def syscall(self, number: SYS, arg1=0, arg2=0, arg3=0, arg4=0, arg5=0, arg6=0) -> int:
        ret = await self.sysif.syscall(number, arg1, arg2, arg3, arg4, arg5, arg6)
        if (self.lose and number == SYS.epoll_ctl
                and arg2 == self.lose[0] and int(arg3) == int(self.lose[1].near)):
            self.lose = None
            self.lost.append(Syscall(number, arg1, arg2, arg3, arg4, arg5, arg6))
            raise SyscallHangup()
        return ret

    async def read(self, src: Pointer) -> bytes:
        return await self.sysif.read(src)

    async def write(self, dest: Pointer, data: bytes) -> None:
        await self.sysif.write(dest, data)

    async def barrier(self) -> None:
        await self.sysif.barrier()

    async def close_interface(self) -> None:
        await self.sysif.close_interface()

    def get_activity_fd(self) -> t.Optional[FileDescriptor]:
        return self.activity_fd

class TestActivityFdHangup(TrioTestCase):
    """A root epoller moves its registration when the activity fd changes, as it does after a
    persistent process reconnects. A SyscallHangup there is retried like one from epoll_wait,
    even when the lost call was performed; before, it escaped the epoller's loop and stopped
    the local event loop."""
    async def lose_response(self, op: EPOLL_CTL, of_new_fd: bool) -> None:
        process = await self.process.fork()
        sysif = SwitchableActivityFdSysif(process.task.sysif)
        process.task.sysif = sysif
        epoller = await Epoller.make_root(process.task)
        await do_async_things(self, epoller, process)
        # A copy of the syscall socket is readable exactly when the original is.
        old_fd = sysif.activity_fd
        placeholder = await process.task.open(await process.ptr("/dev/null"), O.RDONLY)
        new_fd = await old_fd.dup3(placeholder, O.CLOEXEC)
        sysif.lose = (op, new_fd if of_new_fd else old_fd)
        sysif.activity_fd = new_fd
        # This needs epoll_wait in the child to wake up for each new syscall, so it hangs
        # unless the new activity fd ends up registered.
        await do_async_things(self, epoller, process)
        self.assertEqual(len(sysif.lost), 1)

    async def test_lose_del(self) -> None:
        await self.lose_response(EPOLL_CTL.DEL, of_new_fd=False)

    async def test_lose_add(self) -> None:
        await self.lose_response(EPOLL_CTL.ADD, of_new_fd=True)
