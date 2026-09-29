"""pytest configuration for the rsyscall test-suite

Two responsibilities:

* Modules that need a Nix store, the upstream ``nixdeps`` build hook, ``sshd`` or
  special devices are ignored unless ``RSYSCALL_TEST_OPTIONAL=1`` is set. They have
  to be excluded at collection time, because they fail at import; markers can't help.

* If ``RSYSCALL_BASELINE_OUT=<file>`` is set, a sorted ``<STATUS> <nodeid>`` list of
  every collected test is written at session end (see tests/baseline-c.txt). The
  header carries no timestamps or hostnames, so identical runs give identical files.

"""
from __future__ import annotations
import os
import sys

# Excluded by default, with the reason each module cannot run in a plain environment.
OPTIONAL_MODULES = [
    "test_fuse.py",        # /dev/fuse; imports rsyscall.tasks.stub -> rsyscall.nix (nixdeps)
    "test_net.py",         # /dev/net/tun and CAP_NET_ADMIN
    "test_nix.py",         # a working Nix store; imports rsyscall._nixdeps.*
    "test_persistent.py",  # imports rsyscall.tasks.ssh -> rsyscall.nix (nixdeps)
    "test_ssh.py",         # sshd plus Nix; imports rsyscall._nixdeps.*
    "test_stdinboot.py",   # imports rsyscall.tasks.stdin_bootstrap -> rsyscall.nix (nixdeps)
    "test_stub.py",        # imports rsyscall.tasks.stub -> rsyscall.nix (nixdeps)
]
if not os.environ.get("RSYSCALL_TEST_OPTIONAL"):
    collect_ignore = list(OPTIONAL_MODULES)

#### Baseline recorder ####
_RANK = {"PASS": 0, "SKIP": 1, "XFAIL": 1, "XPASS": 2, "FAIL": 3, "ERROR": 4}
_STATUS: dict[str, str] = {}
_DETAIL: dict[str, str] = {}

def _exception_class(report) -> str:
    crash = getattr(report.longrepr, "reprcrash", None)
    if crash is not None:
        text = crash.message
    else:
        lines = str(report.longrepr).strip().splitlines()
        text = lines[-1] if lines else ""
    return text.split(":", 1)[0].strip()[:80]

def _record(nodeid: str, status: str, report=None) -> None:
    if nodeid not in _STATUS or _RANK[status] >= _RANK[_STATUS[nodeid]]:
        _STATUS[nodeid] = status
        if report is not None and status in ("FAIL", "ERROR"):
            _DETAIL[nodeid] = _exception_class(report)

def pytest_collectreport(report):
    if report.failed:
        _record(f"{report.nodeid} (collection)", "ERROR", report)

def pytest_runtest_logreport(report):
    xfail = hasattr(report, "wasxfail")
    if report.when == "call":
        if report.passed:
            _record(report.nodeid, "XPASS" if xfail else "PASS")
        elif report.failed:
            _record(report.nodeid, "FAIL", report)
        else:
            _record(report.nodeid, "XFAIL" if xfail else "SKIP")
    elif report.failed:  # error in setup or teardown
        _record(report.nodeid, "ERROR", report)
    elif report.skipped and report.when == "setup":  # unittest.skip and friends
        _record(report.nodeid, "SKIP")

def pytest_sessionfinish(session, exitstatus):
    out = os.environ.get("RSYSCALL_BASELINE_OUT")
    if not out:
        return
    import pytest
    import trio
    counts = ", ".join(f"{s}={sum(1 for v in _STATUS.values() if v == s)}" for s in _RANK)
    lines = [
        "# rsyscall test baseline. Format: <STATUS> <pytest nodeid> [ # <exception class>]",
        f"# backend={os.environ.get('RSYSCALL_BACKEND', 'c')} python={sys.version_info.major}.{sys.version_info.minor}"
        f" trio={trio.__version__} pytest={pytest.__version__}",
        f"# {len(_STATUS)} entries: {counts}",
    ]
    for nodeid in sorted(_STATUS):
        suffix = f"  # {_DETAIL[nodeid]}" if nodeid in _DETAIL else ""
        lines.append(f"{_STATUS[nodeid]} {nodeid}{suffix}")
    with open(out, "w") as f:
        f.write("\n".join(lines) + "\n")
