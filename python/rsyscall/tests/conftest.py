"""pytest configuration for the rsyscall test-suite

Two responsibilities:

* Modules whose environment is missing on this machine (a Nix store, the OpenSSH executables,
  ``/dev/fuse``, ``pyroute2`` and ``/dev/net/tun``) are ignored at collection time, with the
  reason, unless ``RSYSCALL_TEST_OPTIONAL=1`` is set: they fail at import, so markers can't help.
* If ``RSYSCALL_BASELINE_OUT=<file>`` is set, a sorted ``<STATUS> <nodeid>`` list of every
  collected test is written at session end (see tests/baseline-c.txt). The header carries no
  timestamps or hostnames, so identical runs give identical files; its fourth line records
  which modules were ignored, and why.
"""
from __future__ import annotations
import importlib.util
import os
import shutil
import sys

# Ignored at collection time when what they need is missing on this machine; RSYSCALL_TEST_OPTIONAL=1
# collects them regardless. Each entry lists checks that return None, or the reason (see below).
OPTIONAL_MODULES = {
    "test_fuse.py":       lambda: [_dev("/dev/fuse")],
    "test_net.py":        lambda: [_mod("pyroute2"), _dev("/dev/net/tun")],
    "test_nix.py":        lambda: ["needs a Nix store and the rsyscall._nixdeps closures"],
    "test_persistent.py": lambda: [_exe("ssh"), _exe("sshd"), _exe("ssh-keygen")],
    "test_ssh.py":        lambda: [_exe("ssh"), _exe("sshd"), _exe("ssh-keygen")],
}
SBIN_DIRS = ["/usr/sbin", "/usr/local/sbin", "/sbin"]  # where Debian keeps sshd; rarely on a user's PATH

def _exe(name: str) -> str | None:
    "None when `name` is executable on PATH or in SBIN_DIRS, else the reason"
    path = os.pathsep.join([os.environ.get("PATH", os.defpath), *SBIN_DIRS])
    return None if shutil.which(name, path=path) else f"{name} not found on PATH or in the sbin directories"

def _dev(path: str) -> str | None:
    return None if os.access(path, os.R_OK | os.W_OK) else f"{path} is not readable and writable"

def _mod(name: str) -> str | None:
    return None if importlib.util.find_spec(name) else f"the {name} module is not installed"

IGNORED: dict[str, str] = {}
"module -> why it is not collected on this machine; empty with RSYSCALL_TEST_OPTIONAL=1"
if not os.environ.get("RSYSCALL_TEST_OPTIONAL"):
    for _module, _checks in OPTIONAL_MODULES.items():
        _reasons = [r for r in _checks() if r]
        if _reasons:
            IGNORED[_module] = "; ".join(_reasons)
collect_ignore = sorted(IGNORED)

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
        "# collect_ignore=" + (", ".join(f"{m} ({IGNORED[m]})" for m in sorted(IGNORED)) or "none"),
    ]
    for nodeid in sorted(_STATUS):
        suffix = f"  # {_DETAIL[nodeid]}" if nodeid in _DETAIL else ""
        lines.append(f"{_STATUS[nodeid]} {nodeid}{suffix}")
    with open(out, "w") as f:
        f.write("\n".join(lines) + "\n")
