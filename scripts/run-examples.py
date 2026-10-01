#!/usr/bin/env python3
"""Run every script in examples/ and report PASS, SKIP or FAIL for each.

Usage: run-examples.py [PYTHON]      default: the interpreter running this script

Each example runs from /tmp with unbuffered output, a 60 s timeout, and in a session of its own
whose whole process group is killed once the example exits, so nothing it leaves behind can
outlive the run (see pytest_session.py). Exit status 77 means a prerequisite is missing (SKIP).
Exits 1 if any example fails.
"""
from __future__ import annotations
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = 77
TIMEOUT = 60

def run(python: str, example: Path) -> tuple[str, str]:
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    # Output goes to a file, not a pipe: a process the example leaves behind would keep a pipe
    # open and make reading it wait for the timeout.
    with tempfile.TemporaryFile() as out:
        proc = subprocess.Popen([python, str(example)], cwd="/tmp", env=env, stdout=out,
                                stderr=subprocess.STDOUT, start_new_session=True)
        try:
            proc.wait(timeout=TIMEOUT)
            status = "PASS" if proc.returncode == 0 else "SKIP" if proc.returncode == SKIP else "FAIL"
            note = ""
        except subprocess.TimeoutExpired:
            status, note = "FAIL", f"\n(timed out after {TIMEOUT} s)"
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # whatever the example left behind
        except (ProcessLookupError, PermissionError):
            pass
        proc.wait()
        out.seek(0)
        return status, out.read().decode(errors="replace") + note

def main(argv: list[str]) -> int:
    python = argv[1] if len(argv) > 1 else sys.executable
    failed = 0
    for example in sorted((ROOT / "examples").glob("*.py")):
        status, output = run(python, example)
        print(f"{status:4s}  examples/{example.name}", flush=True)
        if status != "PASS":
            print("\n".join("      " + line for line in output.rstrip().splitlines()[-15:]), flush=True)
        failed += status == "FAIL"
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
