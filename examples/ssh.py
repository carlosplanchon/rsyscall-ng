"""Drive a process on another machine over ssh.

rsyscall sends a small static helper over an ssh connection, starts it on the remote host and
connects to it. From then on the remote process is a Python object here, and every system call
made through it runs on the remote host: this script reads a file there with open and read, then
forks a child there and execs uname in it. Nothing has to be installed on the remote host beyond
a POSIX shell and GNU coreutils.

Usage:  python3 ssh.py HOST     any x86_64 Linux machine you can reach with `ssh HOST`
        python3 ssh.py          a throwaway sshd on this machine, started for the occasion as an
                                ssh ProxyCommand (as the test-suite does); needs ssh, sshd and
                                ssh-keygen installed, but no running ssh server; that sshd
                                may log a harmless "mm_reap" line as its sessions close
"""
import os
import shutil
import sys

import trio

from rsyscall import local_process
from rsyscall.fcntl import O
from rsyscall.sys.wait import W
from rsyscall.tasks.ssh import make_local_ssh, make_ssh_host

SKIP = 77  # exit status for "a prerequisite is missing"
SBIN = ["/usr/sbin", "/usr/local/sbin", "/sbin"]  # where some distributions keep sshd

async def main(host: str | None) -> int:
    if host is None:
        search = os.pathsep.join([os.environ.get("PATH", os.defpath), *SBIN])
        missing = [name for name in ("ssh", "sshd", "ssh-keygen") if not shutil.which(name, path=search)]
        if missing:
            print("missing", ", ".join(missing), "for the local ssh server; pass a HOST instead", file=sys.stderr)
            return SKIP
        ssh_host = await make_local_ssh(local_process)
    else:
        # The function receives the ssh command line and may add any ssh options to it.
        ssh_host = await make_ssh_host(local_process, lambda ssh: ssh.args(host))
    ssh_process, remote = await ssh_host.ssh(local_process)
    try:
        print("remote process:", (await remote.task.getpid()).id)
        # open and read run on the remote host.
        hostname = await remote.task.open(await remote.ptr("/proc/sys/kernel/hostname"), O.RDONLY)
        print("its hostname:", (await remote.read_to_eof(hostname)).decode().strip())
        # So do fork and execve; uname's output comes back over the ssh connection.
        child = await remote.fork()
        uname = await child.environ.which("uname")
        await (await child.exec(uname.args("-srm"))).check()
    finally:
        await remote.exit(0)  # ends the remote process, and with it the ssh session
        await ssh_process.waitpid(W.EXITED)
    return 0

if __name__ == "__main__":
    sys.exit(trio.run(main, sys.argv[1] if len(sys.argv) > 1 else None))
