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
    help="Build native extensions and worker binaries.",
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


def _run(
    command: list[str],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> None:
    subprocess.run(command, cwd=str(cwd) if cwd else None, env=env, check=True)


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


def _rust_speech_host_workspace_dir() -> Path:
    return _REPO_ROOT / "yoyopod_rs"


def _rust_speech_host_crate_dir() -> Path:
    return _rust_speech_host_workspace_dir() / "speech"


def _rust_speech_host_binary_path() -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return _rust_speech_host_crate_dir() / "build" / f"yoyopod-speech-host{suffix}"


def _rust_ui_host_workspace_dir() -> Path:
    return _REPO_ROOT / "yoyopod_rs"


def _rust_ui_host_crate_dir() -> Path:
    return _rust_ui_host_workspace_dir() / "ui"


def _rust_ui_host_binary_path() -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return _rust_ui_host_crate_dir() / "build" / f"yoyopod-ui-host{suffix}"


def _rust_runtime_workspace_dir() -> Path:
    return _REPO_ROOT / "yoyopod_rs"


def _rust_runtime_crate_dir() -> Path:
    return _rust_runtime_workspace_dir() / "runtime"


def _rust_runtime_binary_path() -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return _rust_runtime_crate_dir() / "build" / f"yoyopod-runtime{suffix}"


def _rust_ui_poc_dir() -> Path:
    return _rust_ui_host_crate_dir()


def _rust_ui_poc_binary_path() -> Path:
    return _rust_ui_host_binary_path()


def build_speech_host() -> Path:
    """Build the Rust speech host and return the copied binary path."""

    workspace_dir = _rust_speech_host_workspace_dir()
    output = _rust_speech_host_binary_path()
    output.parent.mkdir(parents=True, exist_ok=True)

    _run(
        [
            "cargo",
            "build",
            "--release",
            "-p",
            "yoyopod-speech",
            "--locked",
        ],
        cwd=workspace_dir,
    )

    suffix = ".exe" if os.name == "nt" else ""
    built_binary = workspace_dir / "target" / "release" / f"yoyopod-speech-host{suffix}"
    shutil.copy2(built_binary, output)
    return output


def build_voice_worker() -> Path:
    """Build the default Rust speech host voice worker."""

    return build_speech_host()


def build_rust_ui_host(*, hardware_feature: bool = True) -> Path:
    """Build the Rust Whisplay UI host and return the copied binary path."""

    workspace_dir = _rust_ui_host_workspace_dir()
    output = _rust_ui_host_binary_path()
    output.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "cargo",
        "build",
        "--release",
        "-p",
        "yoyopod-ui",
        "--locked",
    ]
    if hardware_feature:
        command.extend(["--features", "whisplay-hardware"])
    _run(command, cwd=workspace_dir)

    suffix = ".exe" if os.name == "nt" else ""
    built_binary = workspace_dir / "target" / "release" / f"yoyopod-ui-host{suffix}"
    shutil.copy2(built_binary, output)
    return output


def build_rust_runtime() -> Path:
    """Build the Rust runtime binary and return the copied binary path."""

    workspace_dir = _rust_runtime_workspace_dir()
    output = _rust_runtime_binary_path()
    output.parent.mkdir(parents=True, exist_ok=True)

    _run(
        [
            "cargo",
            "build",
            "--release",
            "-p",
            "yoyopod-runtime",
            "--locked",
        ],
        cwd=workspace_dir,
    )

    suffix = ".exe" if os.name == "nt" else ""
    built_binary = workspace_dir / "target" / "release" / f"yoyopod-runtime{suffix}"
    shutil.copy2(built_binary, output)
    return output


def build_rust_ui_poc(*, hardware_feature: bool = True) -> Path:
    """Compatibility wrapper for the renamed Rust UI host build."""

    return build_rust_ui_host(hardware_feature=hardware_feature)


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
    if binary.stat().st_size == 0:
        return True
    return _newest_mtime(sources) > binary.stat().st_mtime


def _native_artifacts() -> tuple[NativeArtifact, ...]:
    """Return the canonical native artifacts for the current checkout."""

    lvgl_native_dir = _resolve_lvgl_native_dir()
    return (
        NativeArtifact(
            label="LVGL",
            output=lvgl_native_dir / "build" / "libyoyopod_lvgl_shim.so",
            sources=(lvgl_native_dir,),
        ),
    )


def _native_build_dirs() -> tuple[Path, ...]:
    """Return mutable CMake build directories for native artifacts."""

    return (_resolve_lvgl_native_dir() / "build",)


def _clean_native_build_dirs() -> tuple[Path, ...]:
    """Remove mutable native CMake build dirs and return the dirs removed."""

    removed: list[Path] = []
    for build_dir in _native_build_dirs():
        if not build_dir.exists():
            continue
        shutil.rmtree(build_dir)
        removed.append(build_dir)
    return tuple(removed)


def _ensure_native_shims(*, skip_lvgl_fetch: bool = False) -> tuple[str, ...]:
    """Build missing or stale native artifacts and return the labels that were rebuilt."""

    rebuilt: list[str] = []
    lvgl_native_dir = _resolve_lvgl_native_dir()
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
        else:
            raise SystemExit(f"Unknown native artifact: {artifact.label}")
        rebuilt.append(artifact.label)

    return tuple(rebuilt)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command("voice-worker")
def build_voice_worker_command() -> None:
    """Build the Rust speech host voice worker for the current platform."""

    output = build_voice_worker()
    typer.echo(f"Built Rust speech host: {output}")


@app.command("rust-ui-poc")
def build_rust_ui_poc_command(
    no_hardware_feature: Annotated[
        bool,
        typer.Option(
            "--no-hardware-feature",
            help="Build without the whisplay-hardware Cargo feature.",
        ),
    ] = False,
) -> None:
    """Compatibility alias for `yoyopod build rust-ui-host`."""

    output = build_rust_ui_host(hardware_feature=not no_hardware_feature)
    typer.echo(f"Built Rust UI host: {output}")


@app.command("rust-ui-host")
def build_rust_ui_host_command(
    no_hardware_feature: Annotated[
        bool,
        typer.Option(
            "--no-hardware-feature",
            help="Build without the whisplay-hardware Cargo feature.",
        ),
    ] = False,
) -> None:
    """Build the Rust UI host binary."""

    output = build_rust_ui_host(hardware_feature=not no_hardware_feature)
    typer.echo(f"Built Rust UI host: {output}")


@app.command("rust-runtime")
def build_rust_runtime_command() -> None:
    """Build the Rust runtime binary."""

    output = build_rust_runtime()
    typer.echo(f"Built Rust runtime: {output}")


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
    """Build missing or stale native artifacts required by the app."""

    rebuilt = _ensure_native_shims(skip_lvgl_fetch=skip_lvgl_fetch)
    if rebuilt:
        typer.echo(f"Ensured native artifacts: {', '.join(rebuilt)}")
        return
    typer.echo("Native artifacts already current")


@app.command("clean-native")
def clean_native() -> None:
    """Remove mutable native CMake build dirs before a clean rebuild."""

    removed = _clean_native_build_dirs()
    if removed:
        for path in removed:
            typer.echo(f"Removed native build dir: {path}")
        return
    typer.echo("Native build dirs already clean")


@app.command("simulation")
def build_simulation(
    skip_fetch: Annotated[
        bool,
        typer.Option(
            "--skip-fetch",
            help="Skip cloning/updating the pinned LVGL source checkout before rebuilding.",
        ),
    ] = False,
) -> None:
    """Build the LVGL native shim required by ``python yoyopod.py --simulate``."""

    native_dir = _resolve_lvgl_native_dir()
    source_dir = _default_lvgl_source_dir()
    build_dir = native_dir / "build"

    if not skip_fetch:
        _ensure_lvgl_source(source_dir)

    _build_lvgl(native_dir, source_dir, build_dir)
    typer.echo(f"Built simulation LVGL shim in {build_dir}")
