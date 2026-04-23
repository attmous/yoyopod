"""Build a release slot directory from the repo.

Produces:
  <output_root>/<version>/
    ├── app/              # yoyopod + yoyopod_cli source trees
    ├── config/           # repo's top-level config/ tree (default app config)
    ├── venv/             # runtime venv (only when --with-venv)
    ├── bin/launch        # copy of deploy/scripts/launch.sh
    ├── assets/           # currently empty; reserved for fonts/images
    └── manifest.json     # schema-v1 release manifest

SELF-CONTAINED NOTE: venv bundling is ON by default. Build deployable Pi
artifacts in a Linux/aarch64 environment, CI slot builder, or via
`yoyopod remote release build-pi`. Use --skip-venv only for structure tests
or legacy source-only compatibility flows.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import shutil
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

try:
    from yoyopod_cli.release_manifest import (
        Artifact,
        ReleaseManifest,
        Requirements,
        dump_manifest,
    )
    from yoyopod_cli.slot_contract import (
        APP_NATIVE_RUNTIME_ARTIFACTS,
        missing_self_contained_paths,
    )
except ImportError:
    sys.path.insert(0, str(_REPO_ROOT))
    from yoyopod_cli.release_manifest import (  # noqa: E402
        Artifact,
        ReleaseManifest,
        Requirements,
        dump_manifest,
    )
    from yoyopod_cli.slot_contract import (  # noqa: E402
        APP_NATIVE_RUNTIME_ARTIFACTS,
        missing_self_contained_paths,
    )


PACKAGE_DIRS: tuple[str, ...] = ("yoyopod", "yoyopod_cli")


def compute_version(*, fallback_date: str, git_sha: str | None) -> str:
    """Return a version string of the form YYYY.MM.DD-<short-sha|dev>."""
    date_part = fallback_date.replace("-", ".")
    suffix = git_sha[:8] if git_sha else "dev"
    return f"{date_part}-{suffix}"


def _copy_sources(repo_root: Path, dest_app: Path) -> None:
    dest_app.mkdir(parents=True, exist_ok=True)
    for pkg in PACKAGE_DIRS:
        src = repo_root / pkg
        if not src.is_dir():
            raise FileNotFoundError(f"expected source package at {src}")
        shutil.copytree(
            src,
            dest_app / pkg,
            ignore=shutil.ignore_patterns(
                "__pycache__",
                "*.pyc",
                "*.pyo",
                ".pytest_cache",
                ".mypy_cache",
                ".ruff_cache",
                "*.egg-info",
                "*.dist-info",
                ".DS_Store",
            ),
        )
    for native_artifact in APP_NATIVE_RUNTIME_ARTIFACTS:
        shutil.rmtree(dest_app / native_artifact.parent, ignore_errors=True)


def _copy_launcher(repo_root: Path, dest_bin: Path) -> None:
    dest_bin.mkdir(parents=True, exist_ok=True)
    src = repo_root / "deploy" / "scripts" / "launch.sh"
    if not src.exists():
        raise FileNotFoundError(f"launcher script missing: {src}")
    target = dest_bin / "launch"
    launcher_text = src.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    target.write_text(launcher_text, encoding="utf-8", newline="\n")
    target.chmod(0o755)


def _runtime_dependencies(repo_root: Path) -> tuple[str, ...]:
    pyproject_path = repo_root / "pyproject.toml"
    if not pyproject_path.exists():
        raise FileNotFoundError(f"pyproject.toml missing: {pyproject_path}")
    with pyproject_path.open("rb") as handle:
        data = tomllib.load(handle)

    project = data.get("project", {})
    if not isinstance(project, dict):
        raise ValueError(f"[project] must be a TOML table in {pyproject_path}")

    dependencies = project.get("dependencies", [])
    if not isinstance(dependencies, list):
        raise ValueError(f"[project].dependencies must be a TOML array in {pyproject_path}")

    return tuple(str(dep).strip() for dep in dependencies if str(dep).strip())


def _write_runtime_requirements(repo_root: Path, target: Path) -> None:
    requirements = _runtime_dependencies(repo_root)
    contents = "\n".join(requirements)
    if contents:
        contents += "\n"
    target.write_text(contents, encoding="utf-8", newline="\n")


def _venv_python_path(dest_venv: Path) -> Path:
    scripts_dir = "Scripts" if sys.platform == "win32" else "bin"
    python_name = "python.exe" if sys.platform == "win32" else "python"
    return dest_venv / scripts_dir / python_name


def _resolve_python_launcher(python_version: str) -> Path:
    expected = python_version.strip()
    current = f"{sys.version_info.major}.{sys.version_info.minor}"
    if current == expected:
        return Path(sys.executable)

    candidates = [f"python{expected}"]
    if expected.startswith("3."):
        candidates.extend(["python3", "python"])

    for candidate in candidates:
        resolved = shutil.which(candidate)
        if not resolved:
            continue
        result = subprocess.run(
            [
                resolved,
                "-c",
                "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip() == expected:
            return Path(resolved)

    raise FileNotFoundError(
        f"Could not find a Python {expected} interpreter in PATH. "
        "Run this script under the target interpreter or adjust --python-version."
    )


def _resolve_venv(dest_venv: Path, requirements_path: Path, python_version: str) -> None:
    """Create a real venv in dest_venv and install runtime dependencies into it."""
    python_launcher = _resolve_python_launcher(python_version)
    subprocess.run(
        [str(python_launcher), "-m", "venv", str(dest_venv)],
        check=True,
    )
    python_bin = _venv_python_path(dest_venv)
    subprocess.run(
        [
            str(python_bin),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "pip",
            "setuptools",
            "wheel",
        ],
        check=True,
    )
    if requirements_path.stat().st_size == 0:
        return
    subprocess.run(
        [
            str(python_bin),
            "-m",
            "pip",
            "install",
            "-r",
            str(requirements_path),
        ],
        check=True,
    )


def _copy_native_runtime_artifacts(repo_root: Path, dest_app: Path, *, required: bool) -> None:
    """Copy only the runtime `.so` shims into the slot app tree."""

    for relative in APP_NATIVE_RUNTIME_ARTIFACTS:
        src = repo_root / relative
        dest = dest_app / relative
        if not src.is_file():
            if required:
                raise FileNotFoundError(f"required native runtime artifact missing: {src}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def _validate_self_contained_slot(slot_dir: Path) -> None:
    """Raise when the slot does not satisfy the self-contained runtime contract."""

    missing = missing_self_contained_paths(slot_dir)
    if not missing:
        return
    rendered = ", ".join(str(path.as_posix()) for path in missing)
    raise RuntimeError("slot is not self-contained; missing required runtime files: " f"{rendered}")


def _copy_config(repo_root: Path, dest_config: Path) -> None:
    """Copy repo's top-level config/ tree into the slot.

    The launcher cd's to the slot dir before exec, so the app's relative
    config lookups resolve here. State-dir-aware config lookup is a
    separate follow-up; for now config travels with the release.

    *.local.yaml files are excluded — those are dev-machine overrides
    that should not ship to the Pi.
    """
    src = repo_root / "config"
    if not src.is_dir():
        # Tests use minimal fixtures without config/. Skip silently.
        return
    shutil.copytree(
        src,
        dest_config,
        ignore=shutil.ignore_patterns("*.local.yaml", "*.local.*"),
    )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _make_tarball(slot_dir: Path, out_path: Path) -> None:
    with tarfile.open(out_path, "w:gz") as tf:
        tf.add(slot_dir, arcname=slot_dir.name)


def build(
    *,
    repo_root: Path,
    output_root: Path,
    version: str,
    channel: str,
    skip_venv: bool = False,
    python_version: str = "3.12",
) -> Path:
    """Produce a slot directory at <output_root>/<version>/.

    Returns the slot directory path. Venv resolution is enabled by default;
    pass skip_venv=True only for structure tests or legacy source-only slots.
    """
    valid_channels = ("dev", "beta", "stable")
    if channel not in valid_channels:
        raise ValueError(f"channel must be one of {valid_channels}, got {channel!r}")

    slot_dir = output_root / version
    if slot_dir.exists():
        raise FileExistsError(f"output slot already exists: {slot_dir}")
    slot_dir.mkdir(parents=True)

    _copy_sources(repo_root, slot_dir / "app")
    _copy_launcher(repo_root, slot_dir / "bin")
    _copy_config(repo_root, slot_dir / "config")
    _write_runtime_requirements(repo_root, slot_dir / "runtime-requirements.txt")
    (slot_dir / "assets").mkdir(exist_ok=True)
    _copy_native_runtime_artifacts(repo_root, slot_dir / "app", required=not skip_venv)

    if skip_venv:
        (slot_dir / "venv").mkdir()
    else:
        _resolve_venv(slot_dir / "venv", slot_dir / "runtime-requirements.txt", python_version)
        _validate_self_contained_slot(slot_dir)

    tarball = output_root / f"{version}.tar.gz"
    manifest = ReleaseManifest(
        version=version,
        channel=channel,  # type: ignore[arg-type]
        released_at=dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        artifacts={
            "full": Artifact(
                type="full",
                sha256="0" * 64,
                size=0,
                url=None,
                base_version=None,
            ),
        },
        requires=Requirements(min_os_version="0.0.0", min_battery_pct=0, min_free_mb=100),
    )
    dump_manifest(manifest, slot_dir / "manifest.json")
    _make_tarball(slot_dir, tarball)
    manifest = ReleaseManifest(
        version=manifest.version,
        channel=manifest.channel,
        released_at=manifest.released_at,
        artifacts={
            "full": Artifact(
                type="full",
                sha256=_sha256(tarball),
                size=tarball.stat().st_size,
                url=None,
                base_version=None,
            ),
        },
        requires=manifest.requires,
        signature=manifest.signature,
    )
    dump_manifest(manifest, slot_dir / "manifest.json")
    return slot_dir


def _git_sha(repo_root: Path) -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a YoyoPod release slot.")
    parser.add_argument("--output", type=Path, required=True, help="Output root dir")
    parser.add_argument("--channel", choices=["dev", "beta", "stable"], default="dev")
    parser.add_argument("--version", type=str, default=None)
    parser.add_argument(
        "--with-venv",
        action="store_true",
        help="Deprecated compatibility flag; venv bundling is now the default.",
    )
    parser.add_argument(
        "--skip-venv",
        action="store_true",
        help="Create an empty venv placeholder instead of a deployable runtime.",
    )
    parser.add_argument("--python-version", default="3.12")
    args = parser.parse_args()

    repo_root = _REPO_ROOT
    version = args.version or compute_version(
        fallback_date=dt.date.today().isoformat(),
        git_sha=_git_sha(repo_root),
    )
    slot = build(
        repo_root=repo_root,
        output_root=args.output,
        version=version,
        channel=args.channel,
        skip_venv=args.skip_venv,
        python_version=args.python_version,
    )
    print(str(slot))


if __name__ == "__main__":
    main()
