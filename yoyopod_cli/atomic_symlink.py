"""Atomic symlink swap using rename-over-sibling.

On Linux, os.rename(src, dst) is atomic when both are symlinks on the same
filesystem. We never delete the destination first — the rename replaces
it in one syscall, so readers never see a missing link.
"""

from __future__ import annotations

import os
from pathlib import Path


def atomic_symlink(target: Path, link: Path) -> None:
    """Point `link` at `target` atomically.

    `target` must exist. `link` may exist (as a symlink) or not exist.
    If `link` exists as a non-symlink (file or directory), raises
    FileExistsError — we never clobber real paths.

    A sibling temp symlink (`<link>.tmp`) is created and then renamed over
    `link`. If a stale `.tmp` exists from a prior crashed call, it is
    unlinked first.

    Limitations:
    - Single-writer only: not safe when called concurrently from multiple
      processes on the same `link` path.
    - TOCTOU: a real file appearing at `link` between the existence check
      and the rename could be silently clobbered. The single-writer assumption
      prevents this in normal use.
    """
    if not target.exists():
        raise FileNotFoundError(f"symlink target does not exist: {target}")
    if link.exists() and not link.is_symlink():
        raise FileExistsError(f"refusing to clobber non-symlink at {link}")

    tmp = link.with_name(link.name + ".tmp")
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    tmp.symlink_to(target)
    os.rename(tmp, link)
