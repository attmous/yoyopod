"""yoyopod_cli/build.py — build commands for native C extensions."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Optional

import typer

from yoyopod_cli.common import REPO_ROOT

_REPO_ROOT = REPO_ROOT

app = typer.Typer(
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


@dataclass(frozen=True)
class NativeArtifact:
    """One native artifact plus the sources that make it stale."""

    label: str
    output: Path
    sources: tuple[Path, ...]


def _run(command: list[str], cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=str(cwd) if cwd else None, check=True)


def _native_build_jobs() -> str:
    """Return a safe native build parallelism level for the current machine."""

    override = os.environ.get("YOYOPOD_NATIVE_BUILD_JOBS")
    if override:
        return override

    sysconf = getattr(os, "sysconf", None)
    if not callable(sysconf):
        return "2"

    try:
        page_size = int(sysconf("SC_PAGE_SIZE"))
        page_count = int(sysconf("SC_PHYS_PAGES"))
    except (OSError, ValueError):
        return "2"

    total_mib = (page_size * page_count) / (1024 * 1024)
    if total_mib < 1024:
        return "1"
    return "2"


def _resolve_native_dir(label: str, *candidates: Path) -> Path:
    """Return the first native source directory that still exists in this checkout."""

    for candidate in candidates:
        if (candidate / "CMakeLists.txt").exists():
            return candidate

    searched = ", ".join(str(candidate) for candidate in candidates)
    raise SystemExit(f"Could not find the {label} native source directory. Checked: {searched}")


def _resolve_lvgl_native_dir() -> Path:
    """Resolve the LVGL shim native source directory for the current repo layout."""

    return _resolve_native_dir(
        "LVGL",
        _REPO_ROOT / "yoyopod" / "ui" / "lvgl_binding" / "native",
        _REPO_ROOT / "src" / "yoyopod" / "ui" / "lvgl_binding" / "native",
    )


def _resolve_liblinphone_native_dir() -> Path:
    """Resolve the Liblinphone shim native source directory for the current repo layout."""

    return _resolve_native_dir(
        "Liblinphone",
        _REPO_ROOT / "yoyopod" / "backends" / "voip" / "shim_native",
        _REPO_ROOT / "src" / "yoyopod" / "backends" / "voip" / "shim_native",
        _REPO_ROOT
        / "src"
        / "yoyopod"
        / "communication"
        / "integrations"
        / "liblinphone"
        / "native",
    )


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
    _run(["cmake", "--build", str(build_dir), "--parallel", _native_build_jobs()])


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
    _run(["cmake", "--build", str(build_dir), "--parallel", _native_build_jobs()])


def _default_lvgl_source_dir() -> Path:
    """Return the stable cache path for the pinned LVGL source checkout."""

    return _REPO_ROOT / ".cache" / "lvgl" / f"lvgl-{LVGL_VERSION}"


def _newest_mtime(paths: tuple[Path, ...]) -> float:
    """Return the newest file mtime under the provided paths."""

    newest = 0.0
    for path in paths:
        if not path.exists():
            continue
        if path.is_dir():
            for candidate in path.rglob("*"):
                if candidate.is_file():
                    newest = max(newest, candidate.stat().st_mtime)
            continue
        newest = max(newest, path.stat().st_mtime)
    return newest


def _is_stale(binary: Path, sources: tuple[Path, ...]) -> bool:
    """Return True when one native artifact is missing or older than its sources."""

    if not binary.exists():
        return True
    return _newest_mtime(sources) > binary.stat().st_mtime


def _native_artifacts() -> tuple[NativeArtifact, ...]:
    """Return the canonical native artifacts for the current checkout."""

    lvgl_native_dir = _resolve_lvgl_native_dir()
    liblinphone_native_dir = _resolve_liblinphone_native_dir()
    return (
        NativeArtifact(
            label="LVGL",
            output=lvgl_native_dir / "build" / "libyoyopod_lvgl_shim.so",
            sources=(lvgl_native_dir,),
        ),
        NativeArtifact(
            label="Liblinphone",
            output=liblinphone_native_dir / "build" / "libyoyopod_liblinphone_shim.so",
            sources=(liblinphone_native_dir,),
        ),
    )


def _ensure_native_shims(*, skip_lvgl_fetch: bool = False) -> tuple[str, ...]:
    """Build missing or stale native shims and return the labels that were rebuilt."""

    rebuilt: list[str] = []
    lvgl_native_dir = _resolve_lvgl_native_dir()
    liblinphone_native_dir = _resolve_liblinphone_native_dir()
    lvgl_source_dir = _default_lvgl_source_dir()

    for artifact in _native_artifacts():
        if not _is_stale(artifact.output, artifact.sources):
            continue
        if artifact.label == "LVGL":
            if not skip_lvgl_fetch:
                _ensure_lvgl_source(lvgl_source_dir)
            _build_lvgl(
                lvgl_native_dir,
                lvgl_source_dir,
                lvgl_native_dir / "build",
            )
        elif artifact.label == "Liblinphone":
            _build_liblinphone(liblinphone_native_dir, liblinphone_native_dir / "build")
        else:
            raise SystemExit(f"Unknown native artifact: {artifact.label}")
        rebuilt.append(artifact.label)

    return tuple(rebuilt)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command("lvgl")
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
    native_dir = _resolve_lvgl_native_dir()
    resolved_source = source_dir if source_dir is not None else _default_lvgl_source_dir()
    resolved_build = build_dir if build_dir is not None else native_dir / "build"

    if not skip_fetch:
        _ensure_lvgl_source(resolved_source)

    _build_lvgl(native_dir, resolved_source, resolved_build)
    typer.echo(f"Built LVGL shim in {resolved_build}")


@app.command("liblinphone")
def build_liblinphone(
    build_dir: Annotated[
        Optional[Path],
        typer.Option("--build-dir", help="Path to the cmake build output directory."),
    ] = None,
) -> None:
    """Build the native Liblinphone shim for the current platform."""
    native_dir = _resolve_liblinphone_native_dir()
    resolved_build = build_dir if build_dir is not None else native_dir / "build"

    _build_liblinphone(native_dir, resolved_build)
    typer.echo(f"Built Liblinphone shim in {resolved_build}")


@app.command("ensure-native")
def ensure_native(
    skip_lvgl_fetch: Annotated[
        bool,
        typer.Option(
            "--skip-lvgl-fetch",
            help="Do not clone/update the pinned LVGL source checkout before rebuilding.",
        ),
    ] = False,
) -> None:
    """Build missing or stale native shims required by the app."""

    rebuilt = _ensure_native_shims(skip_lvgl_fetch=skip_lvgl_fetch)
    if rebuilt:
        typer.echo(f"Ensured native shims: {', '.join(rebuilt)}")
        return
    typer.echo("Native shims already current")
