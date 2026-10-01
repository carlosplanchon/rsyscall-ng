"""Run a program in a sandbox built from ordinary system calls.

A child is cloned into new user, mount and PID namespaces. Before it runs anything, this
script shapes it with syscalls made from here: it gets an empty root (a tmpfs) holding only
/usr, a fresh /proc for its own PID namespace and one directory of yours at /work, and is
chrooted there. Only then does it exec a shell, which finds itself as PID 1 in a nearly empty
root. The sandbox keeps your user id, so it has no privileges on the host.

Usage:  python3 sandbox.py [DIRECTORY]      (default: the current directory, shown as /work)

Needs unprivileged user namespaces. On Ubuntu 24.04 AppArmor restricts them; see the
kernel.apparmor_restrict_unprivileged_userns sysctl.
"""
import os
import sys

import trio

from rsyscall import local_process
from rsyscall.path import Path
from rsyscall.sched import CLONE
from rsyscall.stdlib import mkdtemp
from rsyscall.sys.mount import MS

SKIP = 77  # exit status for "a prerequisite is missing"

SCRIPT = 'echo "I am PID $$"; echo "/ holds:" $(ls /); echo "/work holds:" $(ls /work | head -n 5)'

async def main(work: Path) -> int:
    # The host process creates the directory that becomes the sandbox's root, and the host
    # process removes it at the end: never let a sandboxed process run that cleanup.
    async with (await mkdtemp(local_process, "sandbox")) as root:
        try:
            sandbox = await local_process.clone(CLONE.NEWUSER|CLONE.NEWNS|CLONE.NEWPID)
        except PermissionError:
            print("unprivileged user namespaces are not available here", file=sys.stderr)
            return SKIP
        async with sandbox.pid:  # if anything below fails, the sandbox is killed
            # Each of these calls runs inside the sandbox, which holds every capability in
            # its own user namespace until it execs.
            await sandbox.mount("tmpfs", root, "tmpfs", MS.NONE, "")
            for name in ("usr", "proc", "work"):
                await sandbox.mkdir(root/name)
            # Bind mounts in a user namespace must be recursive: the host's mounts below them
            # are locked, and a plain bind of a tree with locked submounts fails with EINVAL.
            await sandbox.mount("/usr", root/"usr", "", MS.BIND|MS.REC, "")
            await sandbox.mount(work, root/"work", "", MS.BIND|MS.REC, "")
            # /bin, /lib, ... are symlinks into /usr on merged-/usr systems; recreate them, or
            # bind them if they are real directories.
            for name in ("bin", "sbin", "lib", "lib64"):
                host = "/" + name
                if os.path.islink(host):
                    await sandbox.task.symlink(await sandbox.ptr(os.readlink(host)), await sandbox.ptr(root/name))
                elif os.path.isdir(host):
                    await sandbox.mkdir(root/name)
                    await sandbox.mount(host, root/name, "", MS.BIND|MS.REC, "")
            # A fresh procfs shows only the sandbox's PID namespace. The kernel refuses one in a
            # user namespace where parts of the host's /proc are masked, as in many containers;
            # then bind the host's /proc instead, which shows the host's processes too.
            try:
                await sandbox.mount("proc", root/"proc", "proc", MS.NOSUID|MS.NODEV|MS.NOEXEC, "")
            except PermissionError:
                print("a fresh /proc is not allowed here; binding the host's /proc", file=sys.stderr)
                await sandbox.mount("/proc", root/"proc", "", MS.BIND|MS.REC, "")
            await sandbox.chroot(root)
            await sandbox.task.chdir(await sandbox.ptr("/work"))
            # The shell replaces the sandbox's process: it is PID 1 of the new PID namespace.
            shell = await sandbox.exec(sandbox.environ.sh.args("-c", SCRIPT).env(PATH="/usr/bin:/bin"))
            await shell.check()
    return 0

if __name__ == "__main__":
    work = Path(os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "."))
    sys.exit(trio.run(main, work))
