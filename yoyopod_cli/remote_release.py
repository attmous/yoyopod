"""yoyopod remote release {build-pi,push,rollback,status} - slot-deploy CLI."""

from __future__ import annotations

import shlex
import subprocess
import tarfile
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import typer

from yoyopod_cli.common import checkout_python_path
from yoyopod_cli.paths import SlotPaths, load_pi_paths, load_slot_paths
from yoyopod_cli.release_manifest import ReleaseManifest, load_manifest, validate_release_version
from yoyopod_cli.remote_shared import RemoteConnection, pi_conn
from yoyopod_cli.remote_transport import run_remote, run_remote_capture, validate_config
from yoyopod_cli.slot_contract import is_self_contained_slot, missing_self_contained_paths

app = typer.Typer(name="release", help="Slot-deploy push/rollback/status.", no_args_is_help=True)

# Cache the slot paths per process - load once, not per-helper-call.
_slot_paths_cache: SlotPaths | None = None


@dataclass(frozen=True)
class PreparedSlotArtifact:
    """A local slot artifact materialized into a directory tree."""

    source: Path
    slot_dir: Path
    manifest: ReleaseManifest
    self_contained: bool


@dataclass(frozen=True)
class RemoteBuiltArtifact:
    """Metadata emitted by `remote release build-pi`."""

    build_root: str
    slot_dir: str
    artifact_path: str


def _slots() -> SlotPaths:
    global _slot_paths_cache
    if _slot_paths_cache is None:
        _slot_paths_cache = load_slot_paths()
    return _slot_paths_cache


def _conn(ctx: typer.Context) -> RemoteConnection:
    """Resolve RemoteConnection from typer context (respects --host/--user overrides)."""
    conn = pi_conn(ctx)
    validate_config(conn)  # type: ignore[arg-type]
    return conn


def _slot_dir(version: str) -> str:
    validate_release_version(version)
    return f"{_slots().releases_dir()}/{version}"


def _run_slot_remote(conn: object, command: str, *, tty: bool = False) -> int:
    """Execute one slot-deploy SSH command without depending on a repo checkout."""
    return run_remote(conn, command, tty=tty, workdir=None)  # type: ignore[arg-type]


def _run_slot_remote_capture(conn: object, command: str) -> subprocess.CompletedProcess[str]:
    """Capture one slot-deploy SSH command without depending on a repo checkout."""
    return run_remote_capture(conn, command, workdir=None)  # type: ignore[arg-type]


def _slot_subapp_command(
    base: str,
    module: str,
    *args: str,
    manifest_path: str | None = None,
) -> str:
    """Return a shell command that runs one lightweight yoyopod_cli subapp."""
    python_bin = f"{base}/venv/bin/python"
    app_path = f"{base}/app"
    command_args = " ".join(shlex.quote(arg) for arg in args)
    python_code = shlex.quote(
        f"import sys; sys.path.insert(0, {app_path!r}); from {module} import app; app()"
    )
    manifest_env = (
        f"YOYOPOD_RELEASE_MANIFEST={shlex.quote(manifest_path)} "
        if manifest_path is not None
        else ""
    )
    return (
        f"test -x {shlex.quote(python_bin)} && "
        f"{manifest_env}{shlex.quote(python_bin)} -c {python_code} {command_args}"
    )


def _is_tarball(path: Path) -> bool:
    return path.name.endswith(".tar.gz") or path.suffix == ".tgz"


def _safe_extract_tarball(artifact: Path, destination: Path) -> None:
    """Extract one local tarball after rejecting path traversal entries."""

    destination_root = destination.resolve()
    with tarfile.open(artifact, "r:*") as handle:
        for member in handle.getmembers():
            if member.issym() or member.islnk():
                raise ValueError(f"tarball contains unsafe link: {member.name}")
            if not (member.isdir() or member.isreg()):
                raise ValueError(f"tarball contains unsafe member type: {member.name}")
            target = (destination / member.name).resolve()
            try:
                target.relative_to(destination_root)
            except ValueError as exc:
                raise ValueError(f"tarball contains unsafe path: {member.name}") from exc
        try:
            handle.extractall(destination, filter="data")
        except TypeError:
            handle.extractall(destination)


def _find_materialized_slot_dir(root: Path) -> Path:
    manifests = [candidate.parent for candidate in root.rglob("manifest.json")]
    if len(manifests) != 1:
        raise ValueError(f"expected exactly one slot manifest in {root}, found {len(manifests)}")
    return manifests[0]


@contextmanager
def _prepared_slot_artifact(artifact: Path) -> Iterator[PreparedSlotArtifact]:
    """Yield one slot artifact as a local directory tree plus parsed metadata."""

    if not artifact.exists():
        raise FileNotFoundError(f"release artifact not found: {artifact}")

    tempdir: tempfile.TemporaryDirectory[str] | None = None
    slot_dir: Path
    try:
        if artifact.is_dir():
            slot_dir = artifact
        elif _is_tarball(artifact):
            tempdir = tempfile.TemporaryDirectory(prefix="yoyopod-slot-artifact-")
            extract_root = Path(tempdir.name)
            _safe_extract_tarball(artifact, extract_root)
            slot_dir = _find_materialized_slot_dir(extract_root)
        else:
            raise ValueError(
                f"unsupported release artifact: {artifact} (expected slot dir or .tar.gz)"
            )

        manifest_path = slot_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"manifest.json missing from release artifact: {slot_dir}")

        manifest = load_manifest(manifest_path)
        resolved_slot = slot_dir.resolve()
        yield PreparedSlotArtifact(
            source=artifact,
            slot_dir=resolved_slot,
            manifest=manifest,
            self_contained=is_self_contained_slot(resolved_slot),
        )
    finally:
        if tempdir is not None:
            tempdir.cleanup()


def _rsync_to_pi(conn: RemoteConnection, slot: Path, version: str) -> int:
    """Upload one slot directory to the Pi release store."""
    pi_host: str = getattr(conn, "host", "")
    pi_user: str = getattr(conn, "user", "")
    ssh_target = f"{pi_user}@{pi_host}" if pi_user else pi_host
    release_root = _slots().releases_dir()
    target = f"{ssh_target}:{release_root}/{version}/"
    slot_arg = slot.as_posix().rstrip("/")
    target_dir = f"{release_root}/{version}"
    launch_path = f"{target_dir}/bin/launch"

    rsync_cmd = ["rsync", "-az", "-e", "ssh", "--delete", f"{slot_arg}/", target]
    rsync_result = subprocess.run(rsync_cmd, check=False)
    if rsync_result.returncode == 0:
        return _run_slot_remote(conn, f"chmod 755 {shlex.quote(launch_path)}")

    prepare_remote = _run_slot_remote(
        conn,
        f"rm -rf {shlex.quote(target_dir)} && mkdir -p {shlex.quote(target_dir)}",
    )
    if prepare_remote != 0:
        return prepare_remote

    scp_cmd = ["scp", "-r", f"{slot_arg}/.", f"{ssh_target}:{target_dir}/"]
    scp_result = subprocess.run(scp_cmd, check=False)
    if scp_result.returncode != 0:
        return scp_result.returncode
    return _run_slot_remote(conn, f"chmod 755 {shlex.quote(launch_path)}")


def _run_preflight_on_pi(conn: object, version: str) -> int:
    """Run the preflight health check for the uploaded slot on the Pi."""
    slot_dir = _slot_dir(version)
    cmd = _slot_subapp_command(
        slot_dir,
        "yoyopod_cli.health",
        "preflight",
        "--slot",
        slot_dir,
    )
    return _run_slot_remote(conn, cmd)


def _hydrate_slot_on_pi(conn: object, version: str) -> int:
    """Create a slot-local venv and native shims on the Pi before preflight."""
    slot_dir = _slot_dir(version)
    current_path = _slots().current_path()
    venv_dir = f"{slot_dir}/venv"
    requirements_path = f"{slot_dir}/runtime-requirements.txt"
    tmp_root = f"{_slots().state_dir()}/tmp"
    current_venv = f"{current_path}/venv"
    current_lvgl_build = f"{current_path}/app/yoyopod/ui/lvgl_binding/native/build"
    current_liblinphone_build = f"{current_path}/app/yoyopod/backends/voip/shim_native/build"
    slot_lvgl_build = f"{slot_dir}/app/yoyopod/ui/lvgl_binding/native/build"
    slot_liblinphone_build = f"{slot_dir}/app/yoyopod/backends/voip/shim_native/build"
    current_lvgl_shim = f"{current_lvgl_build}/libyoyopod_lvgl_shim.so"
    current_liblinphone_shim = f"{current_liblinphone_build}/libyoyopod_liblinphone_shim.so"
    slot_lvgl_shim = f"{slot_lvgl_build}/libyoyopod_lvgl_shim.so"
    slot_liblinphone_shim = f"{slot_liblinphone_build}/libyoyopod_liblinphone_shim.so"
    cmd = (
        "set -e; "
        f"test -f {shlex.quote(requirements_path)}; "
        f"mkdir -p {shlex.quote(tmp_root)}; "
        f"export TMPDIR={shlex.quote(tmp_root)}; "
        'tmp_venv=$(mktemp -d "$TMPDIR/yoyopod-slot-venv.XXXXXX"); '
        "trap 'rm -rf \"$tmp_venv\"' EXIT; "
        f"if [ -e {shlex.quote(current_venv)} ]; then "
        f'  cp -aL {shlex.quote(current_venv)}/. "$tmp_venv"/; '
        "else "
        '  python3 -m venv "$tmp_venv"; '
        '  "$tmp_venv/bin/python" -m pip install --upgrade pip setuptools wheel; '
        f"fi; "
        f"if [ -s {shlex.quote(requirements_path)} ]; then "
        f'  "$tmp_venv/bin/python" -m pip install -r {shlex.quote(requirements_path)}; '
        "fi; "
        f"rm -rf {shlex.quote(venv_dir)}; "
        f'mv "$tmp_venv" {shlex.quote(venv_dir)}; '
        "trap - EXIT; "
        f"if [ -f {shlex.quote(current_lvgl_shim)} ]; then "
        f"  rm -rf {shlex.quote(slot_lvgl_build)} && mkdir -p {shlex.quote(slot_lvgl_build)} && "
        f"  cp -aL {shlex.quote(current_lvgl_shim)} {shlex.quote(slot_lvgl_shim)}; "
        f"fi; "
        f"if [ -f {shlex.quote(current_liblinphone_shim)} ]; then "
        f"  rm -rf {shlex.quote(slot_liblinphone_build)} && "
        f"  mkdir -p {shlex.quote(slot_liblinphone_build)} && "
        f"  cp -aL {shlex.quote(current_liblinphone_shim)} "
        f"{shlex.quote(slot_liblinphone_shim)}; "
        f"fi; "
        f"{_slot_subapp_command(slot_dir, 'yoyopod_cli.build', 'ensure-native')}"
    )
    return _run_slot_remote(conn, cmd)


def _flip_symlinks_on_pi(conn: object, version: str) -> int:
    """Atomically flip current -> new version, previous -> old current."""
    new_slot = _slot_dir(version)
    prev_path = _slots().previous_path()
    current_path = _slots().current_path()
    script = (
        "set -e; "
        f"if test -L {shlex.quote(current_path)} && "
        f"prev=$(readlink -e {shlex.quote(current_path)} 2>/dev/null); then "
        f'  ln -sfn "$prev" {shlex.quote(prev_path)}.new && '
        f"  mv -T {shlex.quote(prev_path)}.new {shlex.quote(prev_path)}; "
        "fi; "
        f"ln -sfn {shlex.quote(new_slot)} {shlex.quote(current_path)}.new && "
        f"mv -T {shlex.quote(current_path)}.new {shlex.quote(current_path)} && "
        "sudo systemctl restart yoyopod-slot.service"
    )
    return _run_slot_remote(conn, script)


def _live_status_shell(service: str = "yoyopod-slot.service") -> str:
    """Return a shell snippet that validates the active slot without starting Python."""
    current_path = _slots().current_path()
    service_q = shlex.quote(service)
    current_q = shlex.quote(current_path)
    return (
        f"systemctl is-active --quiet {service_q} && "
        f"pid=$(systemctl show -p MainPID --value {service_q}) && "
        'test -n "$pid" && [ "$pid" != "0" ] && '
        f"cur=$(readlink -f {current_q}) && "
        'cwd=$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true) && '
        'test -n "$cwd" && [ "$cwd" = "$cur" ]'
    )


def _run_live_probe_on_pi(conn: object, version: str, timeout_s: int = 60) -> int:
    """Poll the Pi until the new version reports as live, or timeout."""
    current_path = _slots().current_path()
    live_cmd = _live_status_shell()
    cmd = (
        f"for i in $(seq 1 {timeout_s}); do "
        f"slot=$(readlink -f {shlex.quote(current_path)} 2>/dev/null || true) && "
        f'if {live_cmd} && [ "$(basename "$slot")" = {shlex.quote(version)} ]; then '
        f'echo "version={version}"; exit 0; fi; '
        "sleep 1; done; exit 1"
    )
    return _run_slot_remote(conn, cmd)


def _rollback_on_pi(conn: object) -> int:
    """Invoke the rollback script on the Pi (swaps current <-> previous)."""
    return _run_slot_remote(conn, f"sudo {_slots().bin_dir()}/rollback.sh")


def _status_from_pi(conn: object) -> str:
    """Return the status output from the Pi, or raise typer.Exit on SSH failure."""
    current_path = _slots().current_path()
    previous_path = _slots().previous_path()
    health_cmd = _live_status_shell()
    cmd = (
        f"cur=$(readlink -f {shlex.quote(current_path)} 2>/dev/null || true); "
        f"prev=$(readlink -f {shlex.quote(previous_path)} 2>/dev/null || true); "
        'if [ -n "$cur" ]; then echo current=$(basename "$cur"); else echo current=NONE; fi; '
        'if [ -n "$prev" ]; then echo previous=$(basename "$prev"); else echo previous=NONE; fi; '
        f"echo health=$({health_cmd} >/dev/null 2>&1 && echo ok || echo fail)"
    )
    result = _run_slot_remote_capture(conn, cmd)
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        msg = f"status check failed (exit {result.returncode})"
        if stderr:
            msg += f": {stderr}"
        typer.echo(msg, err=True)
        raise typer.Exit(code=result.returncode if result.returncode else 1)
    return result.stdout


def _cleanup_remote_slot(conn: object, version: str) -> None:
    """Remove a partially-uploaded slot from the Pi."""
    _run_slot_remote(conn, f"rm -rf {shlex.quote(_slot_dir(version))}")


def _check_rollback_available(conn: object) -> int:
    """Return 0 if previous symlink exists as a symlink on the Pi, nonzero otherwise."""
    cmd = f"test -L {shlex.quote(_slots().previous_path())}"
    return _run_slot_remote(conn, cmd)


def _slot_exists_state(conn: object, version: str) -> str:
    """Return one of: 'NEW', 'EXISTS', 'CURRENT'.

    NEW: slot dir doesn't exist on the Pi.
    EXISTS: slot dir exists but is not the active release.
    CURRENT: slot dir exists AND is what `current` resolves to.
    """
    target = _slot_dir(version)
    current_path = _slots().current_path()
    cmd = (
        f"if [ ! -d {shlex.quote(target)} ]; then echo NEW; "
        f'elif [ "$(readlink -f {shlex.quote(current_path)} 2>/dev/null)" = '
        f'"$(readlink -f {shlex.quote(target)} 2>/dev/null)" ]; then echo CURRENT; '
        "else echo EXISTS; fi"
    )
    result = _run_slot_remote_capture(conn, cmd)
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        msg = f"slot state probe failed (exit {result.returncode})"
        if stderr:
            msg += f": {stderr}"
        raise RuntimeError(msg)
    state = result.stdout.strip()
    if state not in {"NEW", "EXISTS", "CURRENT"}:
        raise RuntimeError(f"slot state probe returned unexpected output: {state!r}")
    return state


def _remote_build_pi_command(*, channel: str, version: str | None, python_version: str) -> str:
    """Return one checkout-based remote command that builds a self-contained artifact."""
    pi = load_pi_paths()
    python_bin = shlex.quote(checkout_python_path(pi.venv))
    version_arg = f" --version {shlex.quote(version)}" if version else ""
    return (
        "set -euo pipefail; "
        "build_root=$(mktemp -d /tmp/yoyopod-release-build.XXXXXX); "
        f"{python_bin} -m yoyopod_cli.main build ensure-native; "
        f'slot=$({python_bin} scripts/build_release.py --output "$build_root" --channel '
        f"{shlex.quote(channel)}{version_arg} --with-venv --python-version "
        f"{shlex.quote(python_version)} | tail -n 1); "
        'artifact="${slot}.tar.gz"; '
        'test -f "$artifact"; '
        'printf "YOYOPOD_BUILD_ROOT=%s\\n" "$build_root"; '
        'printf "YOYOPOD_SLOT=%s\\n" "$slot"; '
        'printf "YOYOPOD_ARTIFACT=%s\\n" "$artifact"'
    )


def _parse_tagged_stdout(stdout: str, tag: str) -> str:
    prefix = f"{tag}="
    for line in reversed(stdout.splitlines()):
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped.removeprefix(prefix)
    raise ValueError(f"remote output missing {tag}")


def _build_pi_artifact(
    conn: RemoteConnection,
    *,
    channel: str,
    version: str | None,
    python_version: str,
) -> RemoteBuiltArtifact:
    result = run_remote_capture(
        conn,
        _remote_build_pi_command(
            channel=channel,
            version=version,
            python_version=python_version,
        ),
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        msg = f"remote release build failed (exit {result.returncode})"
        if stderr:
            msg += f": {stderr}"
        raise RuntimeError(msg)
    return RemoteBuiltArtifact(
        build_root=_parse_tagged_stdout(result.stdout, "YOYOPOD_BUILD_ROOT"),
        slot_dir=_parse_tagged_stdout(result.stdout, "YOYOPOD_SLOT"),
        artifact_path=_parse_tagged_stdout(result.stdout, "YOYOPOD_ARTIFACT"),
    )


def _download_remote_artifact(conn: RemoteConnection, remote_path: str, local_path: Path) -> int:
    """Download one remote tarball to the local machine."""
    local_path.parent.mkdir(parents=True, exist_ok=True)
    scp_cmd = ["scp", f"{conn.ssh_target}:{remote_path}", str(local_path)]
    return subprocess.run(scp_cmd, check=False).returncode


def _install_release_from_url(
    conn: object,
    *,
    url: str,
    first_deploy: bool,
    force: bool,
) -> int:
    """Invoke the Pi-side installer script against one published artifact URL."""
    installer = f"{_slots().bin_dir()}/install-release.sh"
    command = [
        "sudo",
        installer,
        f"--root={_slots().root}",
        f"--url={url}",
    ]
    if first_deploy:
        command.append("--first-deploy")
    if force:
        command.append("--force")
    return _run_slot_remote(conn, " ".join(shlex.quote(part) for part in command), tty=True)


@app.command("push")
def push(
    ctx: typer.Context,
    artifact: Path = typer.Argument(
        ...,
        help="Local release slot dir or .tar.gz artifact from build_release.",
    ),
    first_deploy: bool = typer.Option(
        False,
        "--first-deploy",
        help=(
            "Acknowledge there is no rollback path "
            "(required when previous symlink doesn't exist on the Pi)."
        ),
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help=("Overwrite an existing release slot of the same version " "(never the active one)."),
    ),
    hydrate_on_target: bool = typer.Option(
        False,
        "--hydrate-on-target",
        help=(
            "Compatibility escape hatch for older source-only slots that do not bundle "
            "their own runtime venv and native shims."
        ),
    ),
) -> None:
    """Push a pre-built slot dir or tarball to the Pi and atomically switch to it."""
    conn = _conn(ctx)
    try:
        with _prepared_slot_artifact(artifact.resolve()) as prepared:
            manifest = prepared.manifest

            state = _slot_exists_state(conn, manifest.version)
            if state == "CURRENT":
                typer.echo(
                    f"ERROR: slot {manifest.version} is the currently-active release on the Pi.\n"
                    "Refusing to overwrite. Bump the version.",
                    err=True,
                )
                raise typer.Exit(code=2)
            if state == "EXISTS" and not force:
                typer.echo(
                    f"ERROR: slot {manifest.version} already exists on the Pi.\n"
                    "Releases are immutable; bump the version, or pass --force to overwrite "
                    "(only allowed when the slot is not the active release).",
                    err=True,
                )
                raise typer.Exit(code=2)

            if not first_deploy:
                rb_check = _check_rollback_available(conn)
                if rb_check != 0:
                    typer.echo(
                        "ERROR: no rollback path on Pi (previous symlink missing).\n"
                        "If this is the very first deploy, re-run with --first-deploy to acknowledge.\n"
                        "Otherwise, investigate why the previous symlink is gone.",
                        err=True,
                    )
                    raise typer.Exit(code=2)

            if not prepared.self_contained and not hydrate_on_target:
                missing = ", ".join(
                    path.as_posix() for path in missing_self_contained_paths(prepared.slot_dir)
                )
                typer.echo(
                    "ERROR: release artifact is not self-contained.\n"
                    "Missing required runtime files: "
                    f"{missing}\n"
                    "Rebuild it with `--with-venv` in a Linux/aarch64 environment or via "
                    "`yoyopod remote release build-pi`, or re-run with "
                    "`--hydrate-on-target` to use the legacy compatibility path.",
                    err=True,
                )
                raise typer.Exit(code=2)

            host: str = getattr(conn, "host", "")
            user: str = getattr(conn, "user", "")

            typer.echo(f"rsync -> {user}@{host}:{_slots().releases_dir()}/{manifest.version}/")
            rc = _rsync_to_pi(conn, prepared.slot_dir, manifest.version)
            if rc != 0:
                typer.echo("rsync failed -- removing uploaded slot", err=True)
                _cleanup_remote_slot(conn, manifest.version)
                raise typer.Exit(code=rc)

            if prepared.self_contained:
                typer.echo("self-contained slot detected; skipping target hydration")
            else:
                typer.echo("hydrate runtime on target...")
                rc = _hydrate_slot_on_pi(conn, manifest.version)
                if rc != 0:
                    typer.echo("slot hydration failed -- removing uploaded slot", err=True)
                    _cleanup_remote_slot(conn, manifest.version)
                    raise typer.Exit(code=rc)

            typer.echo("preflight...")
            rc = _run_preflight_on_pi(conn, manifest.version)
            if rc != 0:
                typer.echo("preflight failed -- removing uploaded slot", err=True)
                _cleanup_remote_slot(conn, manifest.version)
                raise typer.Exit(code=rc)

            typer.echo("flip + restart...")
            rc = _flip_symlinks_on_pi(conn, manifest.version)
            if rc != 0:
                typer.echo("symlink flip / restart failed", err=True)
                raise typer.Exit(code=rc)

            typer.echo("live probe...")
            rc = _run_live_probe_on_pi(conn, manifest.version)
            if rc != 0:
                typer.echo("live probe failed - rolling back", err=True)
                rb_rc = _rollback_on_pi(conn)
                if rb_rc != 0:
                    typer.echo(
                        f"rollback also failed (exit {rb_rc}) - system state unknown", err=True
                    )
                raise typer.Exit(code=rc)

            typer.echo(f"released {manifest.version}")
    except typer.Exit:
        raise
    except (FileNotFoundError, RuntimeError, ValueError, tarfile.TarError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc


@app.command("rollback")
def rollback(ctx: typer.Context) -> None:
    """Swap current <-> previous on the Pi and restart."""
    conn = _conn(ctx)
    rc = _rollback_on_pi(conn)
    if rc != 0:
        raise typer.Exit(code=rc)
    typer.echo("rollback complete")


@app.command("status")
def status(ctx: typer.Context) -> None:
    """Print current / previous / health from the Pi."""
    conn = _conn(ctx)
    typer.echo(_status_from_pi(conn))


@app.command("build-pi")
def build_pi(
    ctx: typer.Context,
    output: Path = typer.Option(
        Path("build") / "releases",
        "--output",
        help="Local directory that should receive the downloaded .tar.gz artifact.",
    ),
    channel: str = typer.Option("dev", "--channel"),
    version: str | None = typer.Option(None, "--version"),
    python_version: str = typer.Option("3.12", "--python-version"),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite an existing local artifact of the same filename.",
    ),
    keep_remote: bool = typer.Option(
        False,
        "--keep-remote",
        help="Keep the temporary remote build directory on the Pi after download.",
    ),
) -> None:
    """Build a self-contained release artifact on the Pi checkout and download it locally."""

    conn = _conn(ctx)
    typer.echo("build self-contained artifact on target checkout...")
    try:
        built = _build_pi_artifact(
            conn,
            channel=channel,
            version=version,
            python_version=python_version,
        )
    except (RuntimeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    local_output = output.resolve()
    local_output.mkdir(parents=True, exist_ok=True)
    local_artifact = local_output / Path(built.artifact_path).name
    if local_artifact.exists() and not force:
        typer.echo(
            f"local artifact already exists: {local_artifact}\n" "Pass --force to overwrite it.",
            err=True,
        )
        raise typer.Exit(code=2)

    typer.echo(f"download -> {local_artifact}")
    rc = _download_remote_artifact(conn, built.artifact_path, local_artifact)
    if rc != 0:
        typer.echo("download failed", err=True)
        raise typer.Exit(code=rc)

    if not keep_remote:
        cleanup_rc = _run_slot_remote(conn, f"rm -rf {shlex.quote(built.build_root)}")
        if cleanup_rc != 0:
            typer.echo(
                f"warning: remote cleanup failed for {built.build_root} (exit {cleanup_rc})",
                err=True,
            )

    typer.echo(str(local_artifact))


@app.command("install-url")
def install_url(
    ctx: typer.Context,
    url: str = typer.Argument(..., help="HTTPS URL of the published slot tarball."),
    first_deploy: bool = typer.Option(
        False,
        "--first-deploy",
        help=(
            "Acknowledge there is no rollback path yet "
            "(required when previous symlink doesn't exist on the Pi)."
        ),
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite an existing non-active slot version on the Pi.",
    ),
) -> None:
    """Download and install one published slot artifact on the Pi."""

    conn = _conn(ctx)
    rc = _install_release_from_url(
        conn,
        url=url,
        first_deploy=first_deploy,
        force=force,
    )
    if rc != 0:
        raise typer.Exit(code=rc)
