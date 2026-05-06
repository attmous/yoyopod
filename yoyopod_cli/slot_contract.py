"""Shared slot-deploy structural contract helpers."""

from __future__ import annotations

from pathlib import Path

SLOT_REQUIRED_DIRS: tuple[str, ...] = ("venv", "app", "config")
SLOT_VENV_PYTHON = Path("venv") / "bin" / "python"
SLOT_PYTHON_BIN = Path("python") / "bin" / "python3.12"
SLOT_PYTHON_STDLIB_MARKER = Path("python") / "lib" / "python3.12" / "os.py"
SLOT_VOICE_WORKER_ARTIFACT = Path("app") / "device" / "speech" / "build" / "yoyopod-speech-host"

APP_NATIVE_RUNTIME_ARTIFACTS: tuple[Path, ...] = (
    Path("yoyopod") / "ui" / "lvgl_binding" / "native" / "build" / "libyoyopod_lvgl_shim.so",
    Path("yoyopod") / "ui" / "lvgl_binding" / "native" / "build" / "lvgl" / "lib" / "liblvgl.so.9",
    Path("device") / "cloud" / "build" / "yoyopod-cloud-host",
    Path("device") / "media" / "build" / "yoyopod-media-host",
    Path("device") / "voip" / "build" / "yoyopod-voip-host",
    Path("device") / "network" / "build" / "yoyopod-network-host",
    Path("device") / "power" / "build" / "yoyopod-power-host",
    Path("device") / "speech" / "build" / "yoyopod-speech-host",
    Path("device") / "runtime" / "build" / "yoyopod-runtime",
)

SLOT_NATIVE_RUNTIME_ARTIFACTS: tuple[Path, ...] = tuple(
    Path("app") / relative for relative in APP_NATIVE_RUNTIME_ARTIFACTS
)
HYDRATED_RUNTIME_REQUIRED_FILES: tuple[Path, ...] = (
    SLOT_VENV_PYTHON,
    *SLOT_NATIVE_RUNTIME_ARTIFACTS,
)

SELF_CONTAINED_REQUIRED_FILES: tuple[Path, ...] = (
    SLOT_VENV_PYTHON,
    SLOT_PYTHON_BIN,
    SLOT_PYTHON_STDLIB_MARKER,
    *SLOT_NATIVE_RUNTIME_ARTIFACTS,
)


def slot_python_bin(python_version: str = "3.12") -> Path:
    return Path("python") / "bin" / f"python{python_version}"


def slot_python_stdlib_marker(python_version: str = "3.12") -> Path:
    return Path("python") / "lib" / f"python{python_version}" / "os.py"


def self_contained_required_files(python_version: str = "3.12") -> tuple[Path, ...]:
    return (
        SLOT_VENV_PYTHON,
        slot_python_bin(python_version),
        slot_python_stdlib_marker(python_version),
        *SLOT_NATIVE_RUNTIME_ARTIFACTS,
    )


def missing_self_contained_paths(slot_dir: Path, python_version: str = "3.12") -> tuple[Path, ...]:
    """Return the slot-relative files a self-contained release still lacks."""

    required_files = self_contained_required_files(python_version)

    # The launch interpreter must be an actual file inside the slot. A venv
    # symlink to the build host's Python can pass Path.is_file(), but is not
    # portable to the Pi.
    venv_python = slot_dir / SLOT_VENV_PYTHON
    if not venv_python.is_file() or venv_python.is_symlink():
        return (
            SLOT_VENV_PYTHON,
            *(
                relative
                for relative in required_files
                if relative != SLOT_VENV_PYTHON
                if not (slot_dir / relative).is_file()
            ),
        )

    return tuple(
        relative
        for relative in required_files
        if relative != SLOT_VENV_PYTHON
        if not (slot_dir / relative).is_file()
    )


def missing_hydrated_runtime_paths(slot_dir: Path) -> tuple[Path, ...]:
    """Return required files for a legacy Pi-hydrated source slot."""

    return tuple(
        relative
        for relative in HYDRATED_RUNTIME_REQUIRED_FILES
        if not (slot_dir / relative).is_file()
    )


def detect_self_contained_python_version(slot_dir: Path) -> str | None:
    """Return the bundled Python version when a slot satisfies the contract."""

    runtime_bin = slot_dir / "python" / "bin"
    if not runtime_bin.is_dir():
        return None

    for python_bin in sorted(runtime_bin.glob("python3.*")):
        if not python_bin.is_file():
            continue
        version = python_bin.name.removeprefix("python")
        if version and not missing_self_contained_paths(slot_dir, version):
            return version
    return None


def is_self_contained_slot(slot_dir: Path, python_version: str = "3.12") -> bool:
    """Return True when the slot contains its own runtime Python and native artifacts."""

    return not missing_self_contained_paths(slot_dir, python_version)
