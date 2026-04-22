from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from yoyopod_cli.atomic_symlink import atomic_symlink

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only symlink semantics")


def test_creates_new_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "current"
    atomic_symlink(target, link)
    assert link.is_symlink()
    assert link.resolve() == target.resolve()


def test_replaces_existing_symlink(tmp_path: Path) -> None:
    old = tmp_path / "v1"
    old.mkdir()
    new = tmp_path / "v2"
    new.mkdir()
    link = tmp_path / "current"
    atomic_symlink(old, link)
    atomic_symlink(new, link)
    assert link.resolve() == new.resolve()


def test_rejects_non_symlink_existing_path(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "current"
    link.mkdir()  # real directory in the way
    with pytest.raises(FileExistsError):
        atomic_symlink(target, link)


def test_cleans_up_temp_on_retry(tmp_path: Path) -> None:
    """If a previous atomic_symlink crashed mid-flight and left a .tmp, we recover."""
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "current"
    stale_tmp = tmp_path / "current.tmp"
    stale_tmp.symlink_to(target)  # orphan from a prior crashed call
    atomic_symlink(target, link)
    assert link.is_symlink()
    assert not stale_tmp.exists() and not stale_tmp.is_symlink()


def test_rejects_dangling_target(tmp_path: Path) -> None:
    nowhere = tmp_path / "does_not_exist"
    dangling = tmp_path / "dangling"
    dangling.symlink_to(nowhere)
    link = tmp_path / "current"
    with pytest.raises(FileNotFoundError):
        atomic_symlink(dangling, link)


def test_preserves_absolute_target(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "current"
    atomic_symlink(target, link)
    assert os.readlink(link) == str(target)
