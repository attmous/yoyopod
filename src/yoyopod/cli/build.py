"""src/yoyopod/cli/build.py — build commands for native C extensions."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Annotated, Optional

import typer

build_app = typer.Typer(
    name="build",
    help="Build native C extensions.",
    no_args_is_help=True,
)

# ---------------------------------------------------------------------------
# LVGL constants
# ---------------------------------------------------------------------------
LVGL_VERSION = "9.5.0"
LVGL_TAG = f"v{LVGL_VERSION}"
LVGL_REPO = "https://github.com/lvgl/lvgl.git"

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _run(command: list[str], cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=str(cwd) if cwd else None, check=True)


# ---------------------------------------------------------------------------
# LVGL helpers (inlined from scripts/lvgl_build.py)
# ---------------------------------------------------------------------------


def _has_valid_lvgl_source(source_dir: Path) -> bool:
    required_paths = (
        source_dir / "CMakeLists.txt",
        source_dir / ".git",
        source_dir / ".git" / "index",
        source_dir / "src" / "misc" / "lv_ext_data.h",
    )
    if any(not path.exists() for path in required_paths):
        return False

    status = subprocess.run(
        ["git", "-C", str(source_dir), "status", "--short", "--untracked-files=no"],
        check=False,
        capture_output=True,
        text=True,
    )
    return status.returncode == 0 and not status.stdout.strip()


def _ensure_lvgl_source(source_dir: Path) -> None:
    if source_dir.exists():
        if _has_valid_lvgl_source(source_dir):
            return
        shutil.rmtree(source_dir)
    source_dir.parent.mkdir(parents=True, exist_ok=True)
    _run(["git", "clone", "--depth", "1", "--branch", LVGL_TAG, LVGL_REPO, str(source_dir)])


def _build_lvgl(native_dir: Path, source_dir: Path, build_dir: Path) -> None:
    build_dir.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "cmake",
            "-S",
            str(native_dir),
            "-B",
            str(build_dir),
            "-DCMAKE_BUILD_TYPE=Release",
            f"-DLVGL_SOURCE_DIR={source_dir}",
            "-DCONFIG_LV_BUILD_EXAMPLES=OFF",
            "-DCONFIG_LV_BUILD_DEMOS=OFF",
        ]
    )
    _run(["cmake", "--build", str(build_dir), "--parallel", "2"])


# ---------------------------------------------------------------------------
# Liblinphone helpers (inlined from scripts/liblinphone_build.py)
# ---------------------------------------------------------------------------


def _build_liblinphone(native_dir: Path, build_dir: Path) -> None:
    build_dir.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "cmake",
            "-S",
            str(native_dir),
            "-B",
            str(build_dir),
            "-DCMAKE_BUILD_TYPE=Release",
        ]
    )
    _run(["cmake", "--build", str(build_dir), "--parallel", "2"])


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@build_app.command("lvgl")
def build_lvgl(
    source_dir: Annotated[
        Optional[Path],
        typer.Option("--source-dir", help="Path to the LVGL source directory."),
    ] = None,
    build_dir: Annotated[
        Optional[Path],
        typer.Option("--build-dir", help="Path to the cmake build output directory."),
    ] = None,
    skip_fetch: Annotated[
        bool,
        typer.Option("--skip-fetch", help="Skip cloning/updating the LVGL source."),
    ] = False,
) -> None:
    """Build the pinned LVGL shim for the current platform."""
    native_dir = _REPO_ROOT / "src" / "yoyopod" / "ui" / "lvgl_binding" / "native"
    resolved_source = (
        source_dir
        if source_dir is not None
        else _REPO_ROOT / ".cache" / "lvgl" / f"lvgl-{LVGL_VERSION}"
    )
    resolved_build = build_dir if build_dir is not None else native_dir / "build"

    if not skip_fetch:
        _ensure_lvgl_source(resolved_source)

    _build_lvgl(native_dir, resolved_source, resolved_build)
    typer.echo(f"Built LVGL shim in {resolved_build}")


@build_app.command("liblinphone")
def build_liblinphone(
    build_dir: Annotated[
        Optional[Path],
        typer.Option("--build-dir", help="Path to the cmake build output directory."),
    ] = None,
) -> None:
    """Build the native Liblinphone shim for the current platform."""
    native_dir = (
        _REPO_ROOT / "src" / "yoyopod" / "communication" / "integrations" / "liblinphone" / "native"
    )
    resolved_build = build_dir if build_dir is not None else native_dir / "build"

    _build_liblinphone(native_dir, resolved_build)
    typer.echo(f"Built Liblinphone shim in {resolved_build}")
