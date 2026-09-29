"A slightly improved version of `pathlib.PurePosixPath`"
from __future__ import annotations
import pathlib

class Path(pathlib.PurePosixPath):
    """`pathlib.PurePosixPath` under a name that can't be confused with `pathlib.Path`

    We use this as Path, rather than using `pathlib.Path`, to avoid confusion about
    `pathlib.Path`'s filesystem-interaction methods, which are not rsyscall-aware.

    This class is safe to inherit from, even with a different constructor signature
    (see `rsyscall.stdlib.mktemp.TemporaryDirectory`): derived paths are always plain
    `Path`s, see `with_segments`.

    """
    def with_segments(self, *pathsegments) -> Path:
        """Build derived paths as plain `Path`s, whatever subclass `self` is

        Since Python 3.12 pathlib constructs derived paths (`parent`, `/`, `with_name`,
        ...) through this hook, by default as `type(self)(*pathsegments)`. Our subclasses
        carry extra constructor arguments and attributes which make no sense for a derived
        path, so we return a plain `Path` instead. Before 3.12, pathlib bypassed
        `__init__` entirely when deriving paths, with the same practical effect.

        """
        return Path(*pathsegments)
