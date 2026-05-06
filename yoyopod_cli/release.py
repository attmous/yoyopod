"""Versioning and release packaging commands for YoYoPod."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

import typer
from yoyopod_cli.common import REPO_ROOT

app = typer.Typer(
    name="release",
    help="Manage YoYoPod versions and build release artifacts.",
    no_args_is_help=True,
)

_VERSION_FILE = REPO_ROOT / "yoyopod_cli" / "_version.py"
_DIST_DIR = REPO_ROOT / "dist"
_VERSION_PATTERN = re.compile(r'^__version__ = "(?P<version>\d+\.\d+\.\d+)"$', re.MULTILINE)


@dataclass(frozen=True)
class BuiltArtifact:
    """One versioned release artifact."""

    path: Path
    sha256: str


def _run(
    command: list[str],
    *,
    capture_output: bool = False,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd or REPO_ROOT),
        check=True,
        text=True,
        capture_output=capture_output,
    )


def _tracked_worktree_is_clean() -> bool:
    result = _run(
        ["git", "status", "--short", "--untracked-files=no"],
        capture_output=True,
    )
    return not result.stdout.strip()


def _parse_version(version: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if match is None:
        raise typer.BadParameter(f"Expected semantic version 'MAJOR.MINOR.PATCH', got {version!r}.")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def _format_version(parts: tuple[int, int, int]) -> str:
    major, minor, patch = parts
    return f"{major}.{minor}.{patch}"


def _next_version(current: str, part: Literal["major", "minor", "patch"]) -> str:
    major, minor, patch = _parse_version(current)
    if part == "major":
        return _format_version((major + 1, 0, 0))
    if part == "minor":
        return _format_version((major, minor + 1, 0))
    return _format_version((major, minor, patch + 1))


def _replace_version_text(version: str) -> None:
    source = _VERSION_FILE.read_text(encoding="utf-8")
    updated, count = _VERSION_PATTERN.subn(f'__version__ = "{version}"', source, count=1)
    if count != 1:
        raise SystemExit(f"Could not update version in {_VERSION_FILE}")
    _VERSION_FILE.write_text(updated, encoding="utf-8")


def _current_version() -> str:
    source = _VERSION_FILE.read_text(encoding="utf-8")
    match = _VERSION_PATTERN.search(source)
    if match is None:
        raise SystemExit(f"Could not read version from {_VERSION_FILE}")
    return match.group("version")


def _artifact_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _collect_built_artifacts(*, exclude_names: set[str] | None = None) -> tuple[BuiltArtifact, ...]:
    ignored = exclude_names or set()
    built_paths = tuple(sorted(_DIST_DIR.glob("*")))
    return tuple(
        BuiltArtifact(path=path, sha256=_artifact_sha256(path))
        for path in built_paths
        if path.is_file() and not path.name.startswith(".") and path.name not in ignored
    )


def _git_sha() -> str:
    return _run(["git", "rev-parse", "HEAD"], capture_output=True).stdout.strip()


def _release_tag(version: str) -> str:
    return f"v{version}"


def _write_release_metadata(version: str, artifacts: tuple[BuiltArtifact, ...]) -> Path:
    payload = {
        "name": "yoyopod",
        "repo": "yoyopod-core",
        "version": version,
        "tag": _release_tag(version),
        "git_sha": _git_sha(),
        "built_at": datetime.now(tz=UTC).isoformat(),
        "artifacts": [
            {
                "name": artifact.path.name,
                "sha256": artifact.sha256,
                "size": artifact.path.stat().st_size,
            }
            for artifact in artifacts
        ],
    }
    output = _DIST_DIR / "release-metadata.json"
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return output


def _write_checksums(artifacts: tuple[BuiltArtifact, ...]) -> Path:
    output = _DIST_DIR / "SHA256SUMS.txt"
    lines = [f"{artifact.sha256}  {artifact.path.name}" for artifact in artifacts]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def _bundle_prefix(version: str) -> str:
    return f"yoyopod-core-{version}"


def _build_repo_bundle(version: str) -> tuple[Path, Path]:
    prefix = _bundle_prefix(version)
    tarball = _DIST_DIR / f"{prefix}.tar.gz"
    zipball = _DIST_DIR / f"{prefix}.zip"
    _run(
        [
            "git",
            "archive",
            "--format=tar.gz",
            f"--prefix={prefix}/",
            "-o",
            str(tarball),
            "HEAD",
        ]
    )
    _run(
        [
            "git",
            "archive",
            "--format=zip",
            f"--prefix={prefix}/",
            "-o",
            str(zipball),
            "HEAD",
        ]
    )
    return tarball, zipball


@app.command("current")
def current() -> None:
    """Show the current YoYoPod package version and expected tag."""

    version = _current_version()
    typer.echo(f"version: {version}")
    typer.echo(f"tag: {_release_tag(version)}")


@app.command("bump")
def bump(
    part: Annotated[
        Literal["major", "minor", "patch"],
        typer.Argument(help="Semantic version component to increment."),
    ],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview the next version without editing files."),
    ] = False,
) -> None:
    """Increment the shared YoYoPod semantic version."""

    current_version = _current_version()
    next_version = _next_version(current_version, part)
    if dry_run:
        typer.echo(next_version)
        return
    _replace_version_text(next_version)
    typer.echo(f"Bumped version: {current_version} -> {next_version}")


@app.command("set-version")
def set_version(
    version: Annotated[
        str,
        typer.Argument(help="Exact semantic version to write, for example 0.2.0."),
    ],
) -> None:
    """Set the shared YoYoPod semantic version explicitly."""

    _parse_version(version)
    _replace_version_text(version)
    typer.echo(f"Set version: {version}")


@app.command("build")
def build(
    clean: Annotated[
        bool,
        typer.Option("--clean/--no-clean", help="Remove dist/ before building artifacts."),
    ] = True,
    allow_dirty: Annotated[
        bool,
        typer.Option(
            "--allow-dirty",
            help="Allow tracked worktree changes when building local test artifacts.",
        ),
    ] = False,
    check_tag: Annotated[
        str,
        typer.Option(
            "--check-tag",
            help="Fail unless the provided tag matches the current version, e.g. v0.2.0.",
        ),
    ] = "",
) -> None:
    """Build Python distributions plus a full YoYoPod repo release bundle."""

    version = _current_version()
    expected_tag = _release_tag(version)
    if check_tag and check_tag != expected_tag:
        raise SystemExit(
            f"Release tag mismatch: current version {version} expects {expected_tag}, got {check_tag}."
        )
    if not allow_dirty and not _tracked_worktree_is_clean():
        raise SystemExit(
            "Tracked worktree is dirty. Commit or stash changes before building a release, "
            "or rerun with --allow-dirty for a local-only artifact build."
        )

    if clean and _DIST_DIR.exists():
        shutil.rmtree(_DIST_DIR)
    _DIST_DIR.mkdir(parents=True, exist_ok=True)

    _run(["uv", "build", "--out-dir", str(_DIST_DIR)])
    tarball, zipball = _build_repo_bundle(version)

    built_artifacts = _collect_built_artifacts(
        exclude_names={"release-metadata.json", "SHA256SUMS.txt"}
    )
    metadata_path = _write_release_metadata(version, built_artifacts)
    checksum_artifacts = _collect_built_artifacts(exclude_names={"SHA256SUMS.txt"})
    checksums_path = _write_checksums(checksum_artifacts)

    typer.echo(f"Built release artifacts for {expected_tag}")
    typer.echo(f"- python dist: {_DIST_DIR}")
    typer.echo(f"- repo bundle: {tarball.name}, {zipball.name}")
    typer.echo(f"- metadata: {metadata_path.name}")
    typer.echo(f"- checksums: {checksums_path.name}")
