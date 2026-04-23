"""yoyopod remote release {push,rollback,status} — slot-deploy CLI."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import typer

from yoyopod_cli.paths import SlotPaths, load_slot_paths
from yoyopod_cli.release_manifest import load_manifest
from yoyopod_cli.remote_shared import pi_conn
from yoyopod_cli.remote_transport import run_remote, run_remote_capture, validate_config

app = typer.Typer(name="release", help="Slot-deploy push/rollback/status.", no_args_is_help=True)

# Cache the slot paths per process — load once, not per-helper-call.
_slot_paths_cache: SlotPaths | None = None


def _slots() -> SlotPaths:
    global _slot_paths_cache
    if _slot_paths_cache is None:
        _slot_paths_cache = load_slot_paths()
    return _slot_paths_cache


def _conn(ctx: typer.Context) -> object:
    """Resolve RemoteConnection from typer context (respects --host/--user overrides)."""
    conn = pi_conn(ctx)
    validate_config(conn)  # type: ignore[arg-type]
    return conn


def _slot_python_invocation(version: str) -> str:
    """Return the shell prefix to invoke yoyopod_cli from a slot."""
    base = f"{_slots().releases_dir()}/{shlex.quote(version)}"
    return f"PYTHONPATH={base}/app:{base}/venv " f"python3 -m yoyopod_cli"


def _rsync_to_pi(conn: object, slot: Path, version: str) -> int:
    """Rsync a local slot directory to the Pi release store."""
    pi_host: str = getattr(conn, "host", "")
    pi_user: str = getattr(conn, "user", "")
    target = (
        f"{pi_user}@{pi_host}:{_slots().releases_dir()}/{version}/"
        if pi_user
        else f"{pi_host}:{_slots().releases_dir()}/{version}/"
    )
    cmd = ["rsync", "-az", "--delete", f"{slot}/", target]
    return subprocess.run(cmd, check=False).returncode


def _run_preflight_on_pi(conn: object, version: str) -> int:
    """Run the preflight health check for the uploaded slot on the Pi."""
    cmd = (
        f"{_slot_python_invocation(version)} health preflight "
        f"--slot {_slots().releases_dir()}/{shlex.quote(version)}"
    )
    return run_remote(conn, cmd)  # type: ignore[arg-type]


def _flip_symlinks_on_pi(conn: object, version: str) -> int:
    """Atomically flip current → new version, previous → old current."""
    new_slot = f"{_slots().releases_dir()}/{shlex.quote(version)}"
    prev_path = _slots().previous_path()
    current_path = _slots().current_path()
    # Build the entire flip as one shell script. prev is read on the remote
    # side, so we never embed untrusted SSH output into a Python f-string.
    script = (
        f"set -e; "
        f"prev=$(readlink -f {current_path} 2>/dev/null || echo NONE); "
        f'if [ "$prev" != "NONE" ]; then '
        f'  ln -sfn "$prev" {prev_path}.new && '
        f"  mv -T {prev_path}.new {prev_path}; "
        f"fi; "
        f"ln -sfn {new_slot} {current_path}.new && "
        f"mv -T {current_path}.new {current_path} && "
        f"sudo systemctl restart yoyopod-slot.service"
    )
    return run_remote(conn, script)  # type: ignore[arg-type]


def _run_live_probe_on_pi(conn: object, version: str, timeout_s: int = 60) -> int:
    """Poll the Pi until the new version reports as live, or timeout."""
    current_path = _slots().current_path()
    # Live probe runs against the CURRENT slot (after flip), so use current_path
    # to find the active venv.
    cmd = (
        f"for i in $(seq 1 {timeout_s}); do "
        f"out=$(PYTHONPATH={current_path}/app:{current_path}/venv "
        f"python3 -m yoyopod_cli health live 2>/dev/null) && "
        f"echo \"$out\" | grep -q {shlex.quote('version=' + version)} && exit 0; "
        f"sleep 1; done; exit 1"
    )
    return run_remote(conn, cmd)  # type: ignore[arg-type]


def _rollback_on_pi(conn: object) -> int:
    """Invoke the rollback script on the Pi (swaps current ↔ previous)."""
    return run_remote(conn, f"sudo {_slots().bin_dir()}/rollback.sh")  # type: ignore[arg-type]


def _status_from_pi(conn: object) -> str:
    """Retrieve current/previous/health status lines from the Pi."""
    current_path = _slots().current_path()
    previous_path = _slots().previous_path()
    cmd = (
        f"echo current=$(readlink -f {current_path} 2>/dev/null | xargs -n1 basename); "
        f"echo previous=$(readlink -f {previous_path} 2>/dev/null | xargs -n1 basename); "
        f"echo health=$(PYTHONPATH={current_path}/app:{current_path}/venv "
        f"python3 -m yoyopod_cli health live >/dev/null 2>&1 && echo ok || echo fail)"
    )
    proc = run_remote_capture(conn, cmd)  # type: ignore[arg-type]
    return proc.stdout


def _cleanup_remote_slot(conn: object, version: str) -> None:
    """Remove a partially-uploaded slot from the Pi."""
    run_remote(conn, f"rm -rf {_slots().releases_dir()}/{shlex.quote(version)}")  # type: ignore[arg-type]


def _check_rollback_available(conn: object) -> int:
    """Return 0 if previous symlink exists as a symlink on the Pi, nonzero otherwise."""
    cmd = f"test -L {_slots().previous_path()}"
    return run_remote(conn, cmd)  # type: ignore[arg-type]


def _slot_exists_state(conn: object, version: str) -> str:
    """Return one of: 'NEW', 'EXISTS', 'CURRENT'.

    NEW: slot dir doesn't exist on the Pi.
    EXISTS: slot dir exists but is not the active release.
    CURRENT: slot dir exists AND is what `current` resolves to.
    """
    paths = _slots()
    quoted = shlex.quote(version)
    target = f"{paths.releases_dir()}/{quoted}"
    cmd = (
        f"if [ ! -d {target} ]; then echo NEW; "
        f'elif [ "$(readlink -f {paths.current_path()} 2>/dev/null)" = '
        f'"$(readlink -f {target} 2>/dev/null)" ]; then echo CURRENT; '
        f"else echo EXISTS; fi"
    )
    return run_remote_capture(conn, cmd).stdout.strip()  # type: ignore[arg-type]


@app.command("push")
def push(
    ctx: typer.Context,
    slot: Path = typer.Argument(..., help="Local release slot dir from build_release."),
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
) -> None:
    """Push a pre-built slot dir to the Pi and atomically switch to it."""
    manifest_path = slot / "manifest.json"
    if not manifest_path.exists():
        typer.echo(f"not a release slot (no manifest.json): {slot}", err=True)
        raise typer.Exit(code=2)
    try:
        manifest = load_manifest(manifest_path)
    except ValueError as exc:
        typer.echo(f"invalid manifest: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    conn = _conn(ctx)

    # Immutability guard: refuse to overwrite existing slots.
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

    # Pre-flight: confirm a rollback path exists, unless operator opted out.
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

    host: str = getattr(conn, "host", "")
    user: str = getattr(conn, "user", "")

    typer.echo(f"rsync -> {user}@{host}:{_slots().releases_dir()}/{manifest.version}/")
    rc = _rsync_to_pi(conn, slot, manifest.version)
    if rc != 0:
        typer.echo("rsync failed", err=True)
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
        typer.echo("live probe failed — rolling back", err=True)
        rb_rc = _rollback_on_pi(conn)
        if rb_rc != 0:
            typer.echo(f"rollback also failed (exit {rb_rc}) — system state unknown", err=True)
        raise typer.Exit(code=rc)

    typer.echo(f"released {manifest.version}")


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
