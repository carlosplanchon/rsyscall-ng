"""Where the native side lives: `librsyscall.so` and the helper executables.

In a wheel or a plain install they are bundled in this package (see setup.py, bundled mode).
In the repository's development flow (`RSYSCALL_NATIVE=prefix`, `make venv BACKEND=c|rust`)
the extension links against the selected prefix and `RSYSCALL_LIBEXEC_DIR` points at that
prefix's `libexec/rsyscall` directory, which takes precedence here.

"""
from __future__ import annotations
import os
from importlib.resources import files
from pathlib import Path

# The public names; it also keeps librsyscall.so, which is not a Python module, out of tools
# that look for submodules (pdoc).
__all__ = ["HELPERS", "bundled_dir", "libexec_dir", "helper", "library_path"]

HELPERS = ("rsyscall-bootstrap", "rsyscall-stdin-bootstrap", "rsyscall-unix-stub")
"The helper executables of bootstrap-handshakes.md, in the order of the specification"

def bundled_dir() -> Path:
    "The directory of this package on disk"
    return Path(str(files(__name__)))

def libexec_dir() -> Path:
    "The directory holding the helper executables: RSYSCALL_LIBEXEC_DIR if set, else the bundled copies"
    env = os.environ.get("RSYSCALL_LIBEXEC_DIR")
    return Path(env) if env else bundled_dir()

def helper(name: str) -> Path:
    "The absolute path of one helper executable; FileNotFoundError if it is not available"
    if name not in HELPERS:
        raise ValueError(f"unknown rsyscall helper {name!r}; expected one of {HELPERS}")
    path = libexec_dir() / name
    if not path.is_file():
        raise FileNotFoundError(f"{name} is not available in {path.parent} "
                                "(bundled by a wheel build, or set RSYSCALL_LIBEXEC_DIR)")
    return path

def library_path() -> Path | None:
    "The bundled librsyscall.so, or None when the extension was linked against a prefix"
    path = bundled_dir() / "librsyscall.so"
    return path if path.is_file() else None
