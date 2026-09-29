import typing as t

#### Raw syscalls ####
import rsyscall.near.types as near
from rsyscall.near.sysif import SyscallInterface, SyscallHangup
from rsyscall.sys.syscall import SYS

async def _execve(sysif: SyscallInterface,
                  path: near.Address, argv: near.Address, envp: near.Address) -> None:
    try:
        await sysif.syscall(SYS.execve, path, argv, envp)
    except SyscallHangup:
        # the syscall connection hanging up is the expected result of a successful exec
        pass

async def _execveat(sysif: SyscallInterface,
                    dirfd: t.Optional[near.FileDescriptor], path: near.Address,
                    argv: near.Address, envp: near.Address, flags: int) -> None:
    if dirfd is None:
        dirfd = AT.FDCWD # type: ignore
    try:
        await sysif.syscall(SYS.execveat, dirfd, path, argv, envp, flags)
    except SyscallHangup:
        pass

async def _exit(sysif: SyscallInterface, status: int) -> None:
    try:
        await sysif.syscall(SYS.exit, status)
    except SyscallHangup:
        # likewise, the connection hangs up when the process exits
        pass
