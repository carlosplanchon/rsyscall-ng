"""Record the status of every test in the suite, running one interpreter per test.

Why one process per test: the tests share the module-level ``rsyscall.local_process``,
whose trio/dneio state does not survive a test being interrupted, e.g. by
pytest-timeout. In a single pytest process one hanging test poisons everything that
runs after it with ``RuntimeError: Attempted to call run() from inside a run()``.
Isolation makes every line of the baseline independent of the others. Each pytest runs
in a session of its own and the processes it leaves behind are killed afterwards
(see pytest_session.py).

Usage: baseline.py [pytest selection args...]      e.g. ``-k socket`` or a test file
Environment:
  BASELINE_OUT            output file (default tests/baseline-c.txt)
  RSYSCALL_BACKEND        recorded in the header (default c)
  RSYSCALL_TEST_TIMEOUT   seconds per test (default 60)
  RSYSCALL_TEST_OPTIONAL  collect even the modules whose environment is missing (see tests/conftest.py)
  RSYSCALL_TEST_CWD       directory pytest runs in (default: the repository root; wheel-test.sh
                          points it at the installed package's tests directory)
  RSYSCALL_BASELINE_LOGS  per-test logs and partial results (default reference/baseline-logs/)
  RSYSCALL_PYTEST_ARGS    extra arguments for every pytest invocation, e.g. -c and --rootdir
"""
from __future__ import annotations
import os
import re
import shlex
import shutil
import sys
from pathlib import Path

import pytest_session  # scripts/ is sys.path[0] when this file is run as a script

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("BASELINE_OUT", ROOT / "tests" / "baseline-c.txt"))
BACKEND = os.environ.get("RSYSCALL_BACKEND", "c")
TIMEOUT = os.environ.get("RSYSCALL_TEST_TIMEOUT", "60")
CWD = Path(os.environ.get("RSYSCALL_TEST_CWD", ROOT))
EXTRA_ARGS = shlex.split(os.environ.get("RSYSCALL_PYTEST_ARGS", ""))
LOG_DIR = Path(os.environ.get("RSYSCALL_BASELINE_LOGS", ROOT / "reference" / "baseline-logs"))
EXECUTED = ("PASS", "SKIP", "XFAIL", "XPASS", "FAIL")
STATUSES = EXECUTED + ("ERROR",)
NODE_ID = re.compile(r"\S+::\S+")

def run_pytest(args: list[str], part: Path, log: Path) -> int:
    env = dict(os.environ, RSYSCALL_BASELINE_OUT=str(part), RSYSCALL_BACKEND=BACKEND)
    return pytest_session.run([*EXTRA_ARGS, "--tb=short", f"--timeout={TIMEOUT}", *args], log, env=env, cwd=CWD)

HEADER_PREFIXES = ("# backend=", "# collect_ignore=")

def read_part(part: Path) -> tuple[list[str], dict[str, str]]:
    "Return (the header lines worth keeping, {nodeid[  # exc]: STATUS}) from a part file"
    header, entries = [], {}
    if not part.exists():
        return header, entries
    for line in part.read_text().splitlines():
        if line.startswith(HEADER_PREFIXES):
            header.append(line)
        elif line.startswith("#") or not line.strip():
            continue
        else:
            status, rest = line.split(" ", 1)
            entries[rest] = status
    return header, entries

def main(argv: list[str]) -> int:
    selection = argv[1:]
    if LOG_DIR.exists():
        shutil.rmtree(LOG_DIR)
    LOG_DIR.mkdir(parents=True)

    # 1. Collection: records collection errors (e.g. missing optional deps) and lists the tests.
    collect_part, collect_log = LOG_DIR / "collect.part", LOG_DIR / "collect.log"
    run_pytest(["--collect-only", "-q", "--continue-on-collection-errors", *selection], collect_part, collect_log)
    node_ids = [l.strip() for l in collect_log.read_text().splitlines() if NODE_ID.fullmatch(l.strip())]
    header, merged = read_part(collect_part)
    versions = next((l for l in header if l.startswith("# backend=")), f"# backend={BACKEND}")
    ignored = next((l for l in header if l.startswith("# collect_ignore=")), "# collect_ignore=unknown")
    print(f"collected {len(node_ids)} tests; {sum(1 for s in merged.values() if s == 'ERROR')} collection errors;"
          f" {ignored[2:]}", flush=True)

    # 2. One pytest process per test.
    width = len(str(len(node_ids)))
    for i, nid in enumerate(node_ids, 1):
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", nid)[-120:]
        part, log = LOG_DIR / f"{i:0{width}d}.part", LOG_DIR / f"{i:0{width}d}-{safe}.log"
        rc = run_pytest([nid], part, log)
        _, entries = read_part(part)
        if not entries:
            entries = {f"{nid}  # no result, pytest exit status {rc}": "ERROR"}
        merged.update(entries)
        status = max(entries.values(), key=STATUSES.index)
        print(f"[{i:{width}d}/{len(node_ids)}] {status:5s} {nid}", flush=True)

    # 3. Merge, sorted by node id, with a deterministic header.
    if not any(s in EXECUTED for s in merged.values()):
        print("no test was executed (collection failed?); baseline not written", file=sys.stderr)
        return 3
    counts = ", ".join(f"{s}={sum(1 for v in merged.values() if v == s)}" for s in STATUSES)
    lines = [
        "# rsyscall test baseline. Format: <STATUS> <pytest nodeid> [ # <exception class>]",
        f"{versions} isolation=one-process-per-test timeout={TIMEOUT}s",
        f"# {len(merged)} entries: {counts}",
        ignored,
    ]
    lines += [f"{merged[k]} {k}" for k in sorted(merged, key=lambda k: k.split('  #')[0])]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")
    print(f"\nwrote {OUT}\n" + "\n".join(lines[:4]))
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
