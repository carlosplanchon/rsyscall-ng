#!/usr/bin/env python3
"""Generate the HTML API reference of the rsyscall package with pdoc.

Usage: api-docs.py OUTDIR      (run with an interpreter that has rsyscall-ng and pdoc installed)

pdoc looks for a package's submodules through its __all__, and rsyscall's __all__ names classes
and functions, not modules, so on its own pdoc would document the top-level package only. This
script finds the modules on disk and names to pdoc each one that the __all__ of its package
hides, so that pdoc documents all of them except the test-suite (rsyscall.tests), the developer
scripts (rsyscall.scripts), the generated cffi module (rsyscall._raw) and the native library that
a bundled install puts in rsyscall._native. rsyscall._native itself is kept: it is how programs
find the helper executables. For the same reason the page of the top-level package would link
to no module, so the script appends a list of all of them to the package docstring before
rendering; the source file is not touched.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
import sys
import tomllib
import warnings
from pathlib import Path

import pdoc
import pdoc.render

import rsyscall

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/carlosplanchon/rsyscall-ng"
# Modules left out, as regular expressions matched at the start of the module name.
EXCLUDED = [r"rsyscall\.tests(\.|$)", r"rsyscall\.scripts(\.|$)", r"rsyscall\._raw$",
            r"rsyscall\._native\.librsyscall$"]

def module_names() -> list[str]:
    "The rsyscall package and every module below it, found on disk, minus EXCLUDED"
    names = ["rsyscall"]
    def walk(path: list[str], prefix: str) -> None:
        for info in pkgutil.iter_modules(path, prefix):
            if any(re.match(pattern, info.name) for pattern in EXCLUDED):
                continue
            names.append(info.name)
            if info.ispkg:
                walk([str(Path(info.module_finder.path, info.name.rpartition(".")[2]))], info.name + ".")
    walk(list(rsyscall.__path__), "rsyscall.")
    return names

def specs(names: list[str]) -> list[str]:
    "The modules pdoc must be named: those that the __all__ of their package hides from its walk"
    hidden = []
    for name in names:
        package, _, short = name.rpartition(".")
        if not package or short not in getattr(importlib.import_module(package), "__all__", [short]):
            hidden.append(name)
    return hidden

def module_index(names: list[str]) -> str:
    "A Markdown list of the modules, each with the first line of its docstring; private ones last"
    lines = ["", "", "## Modules", ""]
    for name in sorted(names[1:], key=lambda name: ("._" in name, name)):
        doc = inspect.getdoc(importlib.import_module(name))
        summary = doc.strip().splitlines()[0].rstrip(".") if doc and doc.strip() else ""
        lines.append(f"- `{name}`" + (f": {summary}" if summary else ""))
    return "\n".join(lines) + "\n"

def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    out = Path(argv[1])
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    names = module_names()
    # pdoc reads the docstring from the imported module object.
    rsyscall.__doc__ = (inspect.getdoc(rsyscall) or "") + module_index(names)
    pdoc.render.configure(
        docformat="markdown",
        edit_url_map={"rsyscall": f"{REPOSITORY}/blob/v{version}/python/rsyscall/"},
        footer_text=f"rsyscall-ng {version}",
    )
    with warnings.catch_warnings():
        # rsyscall.nix annotates with types of the nixdeps package, which only a Nix build has.
        warnings.filterwarnings("ignore", r"(Failed to run TYPE_CHECKING code while parsing|"
                                          r"Error parsing type annotation) PackageClosure ")
        pdoc.pdoc(*specs(names), output_directory=out)
    print(f"api-docs: {len(names)} modules documented in {out}/")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
