"""`Path`, or `JaneliaPath` if `janelia-pathlib` is installed.

Import `Path` from here instead of `pathlib` anywhere a path should
auto-translate known Janelia file shares to the current OS when the
`janelia` extra is installed, and behave like a plain `pathlib.Path`
otherwise.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type checkers always see plain Path here -- JaneliaPath is a Path
    # subclass, so this annotation is still accurate at runtime whichever
    # branch below actually executes.
    from pathlib import Path
else:
    try:
        from janelia_pathlib import JaneliaPath as Path
    except ImportError:
        from pathlib import Path


def to_linux_str(path: str) -> str:
    """`path`, translated to its Linux form if it's a known Janelia file share path."""
    p = Path(path)
    to_os = getattr(p, "to_os", None)
    if to_os is None:
        return str(p)
    return str(to_os("linux"))


__all__ = ["Path", "to_linux_str"]
