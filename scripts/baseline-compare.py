#!/usr/bin/env python3
"""Compare two baseline files (the tests/baseline-*.txt format) test by test.

Tests are matched by module basename, class and name, so a baseline recorded from the
source tree (python/rsyscall/tests/test_x.py::C::t) compares with one recorded from an
installed package (test_x.py::C::t). Status and exception class must both agree.

Usage: baseline-compare.py EXPECTED ACTUAL [--ignore SUBSTRING]...
Exit status 0 when every test of EXPECTED whose node id contains none of the ignored
substrings has the same result in ACTUAL and ACTUAL has no other tests; 1 otherwise.
"""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path

def parse(path: Path) -> dict[str, str]:
    "{normalised nodeid: 'STATUS[  # exception]'}"
    entries = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        status, rest = line.split(" ", 1)
        nodeid, _, detail = rest.partition("  #")
        parts = nodeid.strip().split("::")
        parts[0] = os.path.basename(parts[0])
        entries["::".join(parts)] = status + (f"  #{detail}" if detail else "")
    return entries

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("expected", type=Path)
    ap.add_argument("actual", type=Path)
    ap.add_argument("--ignore", action="append", default=[], metavar="SUBSTRING",
                    help="leave out the tests whose node id contains SUBSTRING (repeatable)")
    a = ap.parse_args()
    expected = {k: v for k, v in parse(a.expected).items() if not any(s in k for s in a.ignore)}
    actual = parse(a.actual)
    problems = []
    for k, v in sorted(expected.items()):
        if k not in actual:
            problems.append(f"  missing    {k}: expected {v}")
        elif actual[k] != v:
            problems.append(f"  different  {k}: expected {v}, got {actual[k]}")
    for k in sorted(set(actual) - set(expected)):
        problems.append(f"  unexpected {k}: {actual[k]}")
    print(f"{len(expected)} tests expected from {a.expected}, {len(actual)} recorded in {a.actual}"
          + (f" (ignored: {', '.join(a.ignore)})" if a.ignore else ""))
    if problems:
        print("\n".join(problems))
        print(f"baseline-compare: {len(problems)} difference(s)")
        return 1
    print("baseline-compare: identical")
    return 0

if __name__ == "__main__":
    sys.exit(main())
