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
import json
import re
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
        validate_release_version,
    )
    from yoyopod_cli.slot_contract import (
        APP_NATIVE_RUNTIME_ARTIFACTS,
        SLOT_VOICE_WORKER_ARTIFACT,
        missing_self_contained_paths,
    )
except ImportError:
    sys.path.insert(0, str(_REPO_ROOT))
    from yoyopod_cli.release_manifest import (  # noqa: E402
        Artifact,
        ReleaseManifest,
        Requirements,
        dump_manifest,
        validate_release_version,
    )
    from yoyopod_cli.slot_contract import (  # noqa: E402
        APP_NATIVE_RUNTIME_ARTIFACTS,
        SLOT_VOICE_WORKER_ARTIFACT,
        missing_self_contained_paths,
    )


PACKAGE_DIRS: tuple[str, ...] = ("yoyopod", "yoyopod_cli")
_CHECKOUT_VOICE_WORKER_ARTIFACT = SLOT_VOICE_WORKER_ARTIFACT.relative_to("app").as_posix()
_SLOT_VOICE_WORKER_ARTIFACT = SLOT_VOICE_WORKER_ARTIFACT.as_posix()
_CHECKOUT_VOICE_WORKER_RE = re.compile(
    rf"(?<![A-Za-z0-9_./-]){re.escape(_CHECKOUT_VOICE_WORKER_ARTIFACT)}(?![A-Za-z0-9_./-])"
)


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


def _copy_python_runtime(python_launcher: Path, runtime_dir: Path, python_version: str) -> None:
    """Copy the base Python stdlib/binary needed by the slot runtime wrapper."""

    info_script = (
        "import json, sys, sysconfig; "
        "print(json.dumps({"
        "'executable': sys.executable, "
        "'stdlib': sysconfig.get_path('stdlib'), "
        "'libdir': sysconfig.get_config_var('LIBDIR'), "
        "'ldlibrary': sysconfig.get_config_var('LDLIBRARY')"
        "}))"
    )
    result = subprocess.run(
        [str(python_launcher), "-c", info_script],
        check=True,
        capture_output=True,
        text=True,
    )
    info = json.loads(result.stdout)
    executable = Path(str(info["executable"]))
    stdlib = Path(str(info["stdlib"]))
    libdir = Path(str(info["libdir"])) if info.get("libdir") else None
    ldlibrary = str(info.get("ldlibrary") or "")

    runtime_bin = runtime_dir / "bin"
    runtime_lib = runtime_dir / "lib"
    runtime_bin.mkdir(parents=True, exist_ok=True)
    runtime_lib.mkdir(parents=True, exist_ok=True)

    target_python = runtime_bin / f"python{python_version}"
    shutil.copy2(executable, target_python)
    target_python.chmod(0o755)

    stdlib_target = runtime_lib / f"python{python_version}"
    shutil.copytree(
        stdlib,
        stdlib_target,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "site-packages",
            "dist-packages",
            "test",
            "tests",
            "idlelib",
            "tkinter",
            "turtledemo",
        ),
    )

    if libdir is not None and ldlibrary:
        for candidate in libdir.glob(f"{ldlibrary}*"):
            if candidate.is_file():
                shutil.copy2(candidate, runtime_lib / candidate.name)


def _write_python_runtime_wrapper(dest_venv: Path, python_version: str) -> None:
    """Replace venv Python executables with a relocatable bundled-runtime wrapper."""

    wrapper = f"""#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
VENV_DIR="$(dirname "$(dirname "$SCRIPT_PATH")")"
SLOT_DIR="$(dirname "$VENV_DIR")"
RUNTIME_DIR="${{SLOT_DIR}}/python"
SITE_PACKAGES="$(find "${{VENV_DIR}}/lib" -maxdepth 2 -type d -name site-packages | head -n 1)"

export PYTHONHOME="${{RUNTIME_DIR}}"
export LD_LIBRARY_PATH="${{RUNTIME_DIR}}/lib${{LD_LIBRARY_PATH:+:${{LD_LIBRARY_PATH}}}}"
if [ -n "${{SITE_PACKAGES}}" ]; then
    export PYTHONPATH="${{PYTHONPATH:+${{PYTHONPATH}}:}}${{SITE_PACKAGES}}"
fi

exec "${{RUNTIME_DIR}}/bin/python{python_version}" "$@"
"""
    bin_dir = dest_venv / "bin"
    for name in ("python", "python3", f"python{python_version}"):
        target = bin_dir / name
        target.write_text(wrapper, encoding="utf-8", newline="\n")
        target.chmod(0o755)


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
        [str(python_launcher), "-m", "venv", "--copies", str(dest_venv)],
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
    if requirements_path.stat().st_size != 0:
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
    _copy_python_runtime(python_launcher, dest_venv.parent / "python", python_version)
    _write_python_runtime_wrapper(dest_venv, python_version)


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


def _copy_voice_worker_runtime_artifact(repo_root: Path, slot_dir: Path, *, required: bool) -> None:
    """Copy the default voice worker binary when it is not already a native app artifact."""

    if (slot_dir / SLOT_VOICE_WORKER_ARTIFACT).is_file():
        return

    src = repo_root / SLOT_VOICE_WORKER_ARTIFACT
    dest = slot_dir / SLOT_VOICE_WORKER_ARTIFACT
    if not src.is_file():
        if required:
            raise FileNotFoundError(f"required voice worker runtime artifact missing: {src}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def _validate_self_contained_slot(slot_dir: Path, python_version: str) -> None:
    """Raise when the slot does not satisfy the self-contained runtime contract."""

    missing = missing_self_contained_paths(slot_dir, python_version)
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
    _rewrite_slot_voice_worker_argv(dest_config)


def _rewrite_slot_voice_worker_argv(dest_config: Path) -> None:
    """Point the copied default voice worker argv at the slot-root artifact path."""

    assistant_config = dest_config / "voice" / "assistant.yaml"
    if not assistant_config.is_file():
        return

    # Keep this script stdlib-only: CI invokes it with `python -S` before the
    # project and PyYAML are installed.
    text = assistant_config.read_text(encoding="utf-8")
    updated = _CHECKOUT_VOICE_WORKER_RE.sub(_SLOT_VOICE_WORKER_ARTIFACT, text)
    if updated != text:
        assistant_config.write_text(updated, encoding="utf-8", newline="\n")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _slot_payload_digest(slot_dir: Path) -> tuple[str, int]:
    """Return a stable digest of the unpacked slot payload.

    The embedded manifest cannot safely contain the sha256 of the tarball that
    contains that same manifest. Instead, the slot manifest records the payload
    digest for files that become live on disk, excluding manifest.json itself.
    The tarball byte digest is written as a sidecar after archive creation.
    """

    digest = hashlib.sha256()
    total_size = 0
    for path in sorted(slot_dir.rglob("*"), key=lambda item: item.relative_to(slot_dir).as_posix()):
        relative = path.relative_to(slot_dir).as_posix()
        if relative == "manifest.json" or path.is_dir():
            continue

        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        if path.is_symlink():
            target = path.readlink().as_posix()
            payload = target.encode("utf-8")
            digest.update(b"symlink\0")
            digest.update(payload)
            total_size += len(payload)
            continue

        digest.update(b"file\0")
        size = path.stat().st_size
        total_size += size
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
    return digest.hexdigest(), total_size


def _make_tarball(slot_dir: Path, out_path: Path) -> None:
    with tarfile.open(out_path, "w:gz") as tf:
        tf.add(slot_dir, arcname=slot_dir.name)


def _write_tarball_sha256_sidecar(tarball: Path) -> None:
    digest = _sha256(tarball)
    tarball.with_suffix(tarball.suffix + ".sha256").write_text(
        f"{digest}  {tarball.name}\n",
        encoding="utf-8",
    )


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
    validate_release_version(version)

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
    _copy_voice_worker_runtime_artifact(repo_root, slot_dir, required=False)

    if skip_venv:
        (slot_dir / "venv").mkdir()
    else:
        _resolve_venv(slot_dir / "venv", slot_dir / "runtime-requirements.txt", python_version)
        _validate_self_contained_slot(slot_dir, python_version)

    payload_sha256, payload_size = _slot_payload_digest(slot_dir)
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
                sha256=payload_sha256,
                size=payload_size,
                url=None,
                base_version=None,
            ),
        },
        requires=Requirements(min_os_version="0.0.0", min_battery_pct=0, min_free_mb=100),
    )
    dump_manifest(manifest, slot_dir / "manifest.json")
    _make_tarball(slot_dir, tarball)
    _write_tarball_sha256_sidecar(tarball)
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
