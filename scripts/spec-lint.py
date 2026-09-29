#!/usr/bin/env python3
"""Lint the clean-room specification in docs/spec/.

Normative files (wire-protocol.md, native-abi.md, bootstrap-handshakes.md): every paragraph or
table row that contains an RFC 2119 keyword (MUST, MUST NOT, SHOULD, SHOULD NOT, MAY; upper
case only) must carry at least one citation of the form ``python/<file>:<line>[-<line>]``,
unless the paragraph is a non-normative block starting with ``Rationale:`` or
``Python-side behaviour:``.  Every citation must name an existing file and a line number
within it.  Fenced code blocks are not linted.

Non-normative files (evolution-notes.md, provenance-map.md): any upper-case RFC keyword outside
backticks or double quotes is an error.

Exit status is non-zero on any failure; diagnostics are ``file:line: message``.
"""
from __future__ import annotations
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs" / "spec"
NORMATIVE = ["wire-protocol.md", "native-abi.md", "bootstrap-handshakes.md"]
NON_NORMATIVE = ["evolution-notes.md", "provenance-map.md"]

RFC = re.compile(r"\b(MUST|SHOULD|MAY)( NOT)?\b")
CITATION = re.compile(r"python/[\w./-]+:\d+(?:-\d+)?")
NON_NORMATIVE_MARKERS = ("Rationale:", "Python-side behaviour:")
MARKUP_PREFIX = re.compile(r"^[\s>*_`-]*")  # blockquote, list, emphasis markers before the marker


def blocks(lines: list[str]):
    """Yield (first_line_number, text) for every paragraph and every table row; skip fenced code."""
    in_code = False
    para: list[str] = []
    start = 0
    for i, line in enumerate(lines, 1):
        if line.strip().startswith("```"):
            if para:
                yield start, "\n".join(para)
                para = []
            in_code = not in_code
            continue
        if in_code:
            continue
        stripped = line.strip()
        if stripped.startswith("|"):
            if para:
                yield start, "\n".join(para)
                para = []
            if not re.fullmatch(r"\|[\s:|-]+\|?", stripped):  # not a separator row
                yield i, line
            continue
        if not stripped:
            if para:
                yield start, "\n".join(para)
                para = []
            continue
        if not para:
            start = i
        para.append(line)
    if para:
        yield start, "\n".join(para)


def check_citation(cite: str, where: str, errors: list[str]) -> None:
    path, _, lines_spec = cite.rpartition(":")
    file = ROOT / path
    if not file.exists():
        errors.append(f"{where}: cited file does not exist: {cite}")
        return
    count = len(file.read_text(errors="replace").splitlines())
    nums = [int(n) for n in lines_spec.split("-")]
    if len(nums) == 2 and nums[0] > nums[1]:
        errors.append(f"{where}: inverted line range: {cite}")
    for n in nums:
        if n < 1 or n > count:
            errors.append(f"{where}: line {n} is outside {path} ({count} lines): {cite}")


def lint_normative(path: pathlib.Path, errors: list[str]) -> None:
    lines = path.read_text().splitlines()
    rel = path.relative_to(ROOT)
    for lineno, text in blocks(lines):
        where = f"{rel}:{lineno}"
        for cite in CITATION.findall(text):
            check_citation(cite, where, errors)
        if not RFC.search(text):
            continue
        head = MARKUP_PREFIX.sub("", text.lstrip())
        if head.startswith(NON_NORMATIVE_MARKERS):
            continue
        if not CITATION.search(text):
            kw = RFC.search(text).group(0)
            errors.append(f"{where}: '{kw}' without a python/<file>:<line> citation")


def lint_non_normative(path: pathlib.Path, errors: list[str]) -> None:
    rel = path.relative_to(ROOT)
    in_code = False
    for lineno, line in enumerate(path.read_text().splitlines(), 1):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        visible = re.sub(r"`[^`]*`", "", line)
        visible = re.sub(r'"[^"]*"', "", visible)
        m = RFC.search(visible)
        if m:
            errors.append(f"{rel}:{lineno}: RFC keyword '{m.group(0)}' in a non-normative document (put it in backticks or quotes)")


def main() -> int:
    errors: list[str] = []
    for name in NORMATIVE:
        path = SPEC / name
        if not path.exists():
            errors.append(f"{path.relative_to(ROOT)}: missing normative file")
            continue
        lint_normative(path, errors)
    for name in NON_NORMATIVE:
        path = SPEC / name
        if not path.exists():
            errors.append(f"{path.relative_to(ROOT)}: missing file")
            continue
        lint_non_normative(path, errors)
    for e in errors:
        print(e)
    if errors:
        print(f"spec-lint: {len(errors)} problem(s)")
        return 1
    print("spec-lint: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
