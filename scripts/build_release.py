"""Build a self-contained release slot directory from the repo.

Produces:
  <output_root>/<version>/
    ├── app/              # yoyopod + yoyopod_cli source trees
    ├── config/           # repo's top-level config/ tree (default app config)
    ├── venv/             # uv-resolved site-packages (only when --with-venv)
    ├── bin/launch        # copy of deploy/scripts/launch.sh
    ├── assets/           # currently empty; reserved for fonts/images
    └── manifest.json     # schema-v1 release manifest

VENV NOTE: --with-venv is OFF by default. Cross-compiling a Pi-aarch64
venv from a dev machine is unreliable because not every YoyoPod dep
ships an aarch64 wheel and source builds for the target can't run on
the host. Without --with-venv, the slot ships an empty venv/ dir and
the launcher falls back to the Pi's system Python (which already has
deps installed via the legacy `uv sync` flow). Use --with-venv only
when running this script in a proper Linux/aarch64 build environment
(CI runner, qemu, buildx container).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

try:
    from yoyopod_cli.release_manifest import (
        Artifact,
        ReleaseManifest,
        Requirements,
        dump_manifest,
    )
except ImportError:
    sys.path.insert(0, str(_REPO_ROOT))
    from yoyopod_cli.release_manifest import (  # noqa: E402
        Artifact,
        ReleaseManifest,
        Requirements,
        dump_manifest,
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
                "__pycache__", "*.pyc", "*.pyo",
                ".pytest_cache", ".mypy_cache", ".ruff_cache",
                "*.egg-info", "*.dist-info",
                ".DS_Store",
            ),
        )


def _copy_launcher(repo_root: Path, dest_bin: Path) -> None:
    dest_bin.mkdir(parents=True, exist_ok=True)
    src = repo_root / "deploy" / "scripts" / "launch.sh"
    if not src.exists():
        raise FileNotFoundError(f"launcher script missing: {src}")
    target = dest_bin / "launch"
    shutil.copy(src, target)
    target.chmod(0o755)


def _resolve_venv(repo_root: Path, dest_venv: Path, python_version: str) -> None:
    """Resolve aarch64 wheels into dest_venv/.

    Builds the project as a wheel first (uv pip install with --only-binary
    cannot build sdists), then installs the wheel and its transitive
    dependencies. Requires network access for transitive deps.
    Tests use skip_venv=True to avoid this path.
    """
    dest_venv.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as wheel_tmp:
        subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", wheel_tmp, str(repo_root)],
            check=True,
        )
        wheels = list(Path(wheel_tmp).glob("*.whl"))
        if not wheels:
            raise RuntimeError(f"uv build produced no wheel in {wheel_tmp}")
        wheel = wheels[0]
        subprocess.run(
            [
                "uv", "pip", "install",
                "--target", str(dest_venv),
                "--python-version", python_version,
                "--only-binary", ":all:",
                str(wheel),
            ],
            check=True,
        )


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
    skip_venv: bool = True,
    python_version: str = "3.12",
) -> Path:
    """Produce a slot directory at <output_root>/<version>/.

    Returns the slot directory path. Venv resolution is skipped by default
    (skip_venv=True); pass skip_venv=False only in a Linux/aarch64 build
    environment where cross-compile constraints can be satisfied.
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
    (slot_dir / "assets").mkdir(exist_ok=True)

    if skip_venv:
        (slot_dir / "venv").mkdir()
    else:
        _resolve_venv(repo_root, slot_dir / "venv", python_version)

    tarball = output_root / f"{version}.tar.gz"
    _make_tarball(slot_dir, tarball)

    manifest = ReleaseManifest(
        version=version,
        channel=channel,  # type: ignore[arg-type]
        released_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        ),
        artifacts={
            "full": Artifact(
                type="full",
                sha256=_sha256(tarball),
                size=tarball.stat().st_size,
                url=None,
                base_version=None,
            ),
        },
        requires=Requirements(min_os_version="0.0.0", min_battery_pct=0, min_free_mb=100),
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
        help=(
            "Resolve and bundle a venv into the slot. OFF by default — "
            "cross-platform venv resolution is unreliable; the slot launcher "
            "falls back to the Pi's system Python. Use this only in a Linux/"
            "aarch64 build environment."
        ),
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
        skip_venv=not args.with_venv,
        python_version=args.python_version,
    )
    print(str(slot))


if __name__ == "__main__":
    main()
