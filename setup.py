"""Build hooks that pyproject.toml cannot express.

Two things need code: the cffi extension ``rsyscall._raw`` (API mode, compiled from
python/ffibuilder.py through ``cffi_modules``) and, in the default *bundled* mode, the Rust
native side, built with cargo and shipped inside the ``rsyscall._native`` package.

RSYSCALL_NATIVE selects the mode:

  bundled   (default) ``cargo build --release`` of native/, the artefacts copied into
            python/rsyscall/_native/, the extension linked with an rpath of $ORIGIN/_native.
            This is what wheels and a plain ``pip install`` use. Nothing under reference/ is
            involved: the library, the executables and the header all come from native/.
  prefix    link against an installed prefix found with pkg-config (PKG_CONFIG_PATH), as
            ``make venv BACKEND=c|rust`` does for the differential testing; the helper
            executables then come from RSYSCALL_LIBEXEC_DIR at run time (scripts/env.sh).

Nobody runs this file directly; the PEP 517 backend (setuptools.build_meta) does.
"""
import os
import shutil
import subprocess
from pathlib import Path

from setuptools import setup
from setuptools.command.build_ext import build_ext as _build_ext
from setuptools.command.build_py import build_py as _build_py

ROOT = Path(__file__).resolve().parent
NATIVE = ROOT / "native"
NATIVE_PKG = ROOT / "python" / "rsyscall" / "_native"
ARTEFACTS = ["librsyscall.so", "rsyscall-bootstrap", "rsyscall-stdin-bootstrap", "rsyscall-unix-stub"]
MODE = os.environ.get("RSYSCALL_NATIVE", "bundled")


def build_native() -> None:
    "Build native/ with cargo and copy the artefacts into python/rsyscall/_native/."
    cargo = os.environ.get("CARGO", "cargo")
    subprocess.run(
        [cargo, "build", "--release", "--manifest-path", str(NATIVE / "Cargo.toml"), "-p", "rsyscall-native"],
        check=True,
    )
    target = NATIVE / "target" / "release"
    NATIVE_PKG.mkdir(exist_ok=True)
    for name in ARTEFACTS:
        shutil.copy2(target / name, NATIVE_PKG / name)  # copy2 keeps the executable bits


class build_py(_build_py):
    def run(self):
        if MODE == "bundled":
            build_native()
        super().run()


class build_ext(_build_ext):
    def run(self):
        # Editable installs may build the extension without build_py; the library must
        # exist in native/target/release before the extension is linked against it.
        if MODE == "bundled" and not (NATIVE / "target" / "release" / "librsyscall.so").exists():
            build_native()
        super().run()


setup(
    cmdclass={"build_py": build_py, "build_ext": build_ext},
    cffi_modules=["python/ffibuilder.py:ffibuilder"],
    # The cffi extension uses the limited API, so one wheel serves every CPython >= 3.12.
    options={"bdist_wheel": {"py_limited_api": "cp312"}},
)
