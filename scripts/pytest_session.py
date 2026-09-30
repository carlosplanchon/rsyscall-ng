#!/usr/bin/env python3
"""Run pytest in a session of its own and kill whatever it leaves behind.

rsyscall tests create processes that share the interpreter's address space and hold
both ends of their syscall sockets, so they outlive pytest whenever a test is
interrupted or does not tear them down. Each orphan keeps the inherited stdout open,
which makes any ``make ... | tail`` wait forever, and they pile up by the hundred.
pytest is therefore started as the leader of a new session (which also means no
controlling terminal: nothing can block on a prompt, e.g. sudo in test_setuid), its
output goes to a log file, and the whole process group is killed once it has exited.

Usage:  pytest_session.py LOGFILE [pytest arguments...]      exit status: pytest's
Import: run(args, log, env=None, cwd=None) -> int
"""
from __future__ import annotations
import os
import signal
import subprocess
import sys
from pathlib import Path

def run(args: list[str], log: Path | str, env: dict[str, str] | None = None, cwd=None) -> int:
    "Run ``python -m pytest -p no:cacheprovider *args`` with its output in ``log``; return its exit status"
    cmd = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args]
    with open(log, "w") as f:
        f.write(" ".join(cmd) + "\n\n")
        f.flush()
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT,
                                start_new_session=True)
        status = proc.wait()
    # The leader is gone, but its process group id lives on as long as any orphan does.
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # nothing was left behind
    return status

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(run(sys.argv[2:], sys.argv[1]))
