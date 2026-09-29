"A slightly improved version of `pathlib.PurePosixPath`"
from __future__ import annotations
import pathlib

class Path(pathlib.PurePosixPath):
    """`pathlib.PurePosixPath` under a name that can't be confused with `pathlib.Path`

    We use this as Path, rather than using `pathlib.Path`, to avoid confusion about
    `pathlib.Path`'s filesystem-interaction methods, which are not rsyscall-aware.

    Older versions of this class overrode `__new__` and `__init__` to work around
    pathlib internals that made subclassing fragile. Since Python 3.12 pathlib is
    designed to be subclassed (`with_segments`), so no constructor tricks are
    needed; `Path / "x"` still returns a `Path`.

    """
