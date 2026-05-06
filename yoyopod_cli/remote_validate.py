"""Remote validate + preflight — run Pi validation stages over SSH.

Absorbs previous `remote lvgl-soak` as `--with-lvgl-soak`,
previous `remote navigation-soak` as `--with-navigation`.
"""

from __future__ import annotations

import typer

from yoyopod_cli.common import checkout_module_command, configure_logging
from yoyopod_cli.paths import load_pi_paths
from yoyopod_cli.remote_shared import build_remote_app, pi_conn
from yoyopod_cli.remote_transport import (
    run_local,
    run_local_capture,
    run_remote,
    shell_quote,
    validate_config,
)

app = build_remote_app("validate_app", "Validate commit + health on the Pi.")

_RUST_UI_HOST_WORKER = "device/ui/build/yoyopod-ui-host"
_RUST_UI_POC_WORKER = _RUST_UI_HOST_WORKER
_RUST_RUNTIME_WORKER = "device/runtime/build/yoyopod-runtime"
_RUST_CLOUD_HOST_WORKER = "device/cloud/build/yoyopod-cloud-host"
_RUST_MEDIA_HOST_WORKER = "device/media/build/yoyopod-media-host"
_RUST_VOIP_HOST_WORKER = "device/voip/build/yoyopod-voip-host"


def _build_preflight_steps() -> list[tuple[str, list[str]]]:
    """Preflight steps as (label, argv) tuples. Run them sequentially; exit on first failure."""
    return [
        ("git diff clean", ["git", "diff", "--quiet"]),
        ("git diff staged", ["git", "diff", "--cached", "--quiet"]),
        ("quality gate", ["uv", "run", "python", "scripts/quality.py", "ci"]),
    ]


def _require_local_check(command: list[str], *, message: str) -> None:
    """Run one local git check and abort with a clear CLI error when it fails."""
    result = run_local_capture(command)
    if result.returncode == 0:
        return
    typer.echo(message, err=True)
    stderr = result.stderr.strip()
    if stderr:
        typer.echo(stderr, err=True)
    raise typer.Exit(1)


def _require_local_revision_ready(branch: str, sha: str) -> None:
    """Enforce the committed-code contract before any remote validation runs."""
    _require_local_check(
        ["git", "diff", "--quiet"],
        message=(
            "Local worktree has uncommitted changes. Commit or stash them before "
            "`yoyopod remote validate`."
        ),
    )
    _require_local_check(
        ["git", "diff", "--cached", "--quiet"],
        message=(
            "Local index has staged but uncommitted changes. Commit or stash them before "
            "`yoyopod remote validate`."
        ),
    )
    _require_local_check(
        ["git", "fetch", "--quiet", "origin", branch],
        message=f"Failed to fetch `origin/{branch}` before remote validation.",
    )
    _require_local_check(
        ["git", "rev-parse", "--verify", f"origin/{branch}^{{commit}}"],
        message=(
            f"Branch `{branch}` is not available on origin. Push it before "
            "`yoyopod remote validate`."
        ),
    )
    if sha:
        _require_local_check(
            ["git", "merge-base", "--is-ancestor", sha, f"origin/{branch}"],
            message=(
                f"Commit `{sha}` is not reachable from `origin/{branch}`. "
                "Push it or choose a pushed SHA before remote validation."
            ),
        )
        return

    local_branch_ref = f"refs/heads/{branch}"
    local_branch = run_local_capture(["git", "show-ref", "--verify", "--quiet", local_branch_ref])
    if local_branch.returncode != 0:
        return

    ahead = run_local_capture(["git", "rev-list", "--count", f"origin/{branch}..{branch}"])
    if ahead.returncode != 0:
        typer.echo(
            f"Failed to compare local `{branch}` against `origin/{branch}` before remote validation.",
            err=True,
        )
        stderr = ahead.stderr.strip()
        if stderr:
            typer.echo(stderr, err=True)
        raise typer.Exit(1)
    if ahead.stdout.strip() != "0":
        typer.echo(
            f"Local branch `{branch}` has unpushed commits. Push it or pass --sha for a pushed commit before remote validation.",
            err=True,
        )
        raise typer.Exit(1)


def _build_validate(
    *,
    branch: str,
    venv_relpath: str = ".venv",
    sha: str = "",
    with_voip: bool,
    with_cloud_voice: bool = False,
    with_lvgl_soak: bool,
    with_navigation: bool,
    with_voip_call_soak: bool = False,
    voip_soak_target: str = "",
    voip_soak_seconds: float = 300.0,
    with_rust_ui_host: bool = False,
    with_rust_ui_poc: bool = False,
) -> str:
    """Shell that fast-forwards the branch on the Pi, then runs staged validation.

    When *sha* is provided the checkout is pinned to that commit (ancestry check
    ensures it is reachable from origin/<branch>). Without a SHA the branch tip
    on origin is used.
    """
    br = shell_quote(branch)
    origin_br = shell_quote(f"origin/{branch}")
    steps = [
        "git fetch --prune origin",
        "git clean -fd",
        f"git checkout --force -B {br} {origin_br}",
    ]
    if sha:
        sh = shell_quote(sha)
        # Fail fast when the SHA is not reachable from the target branch.
        steps.append(f"git merge-base --is-ancestor {sh} {origin_br}")
        steps.append(f"git reset --hard {sh}")
    else:
        steps.append(f"git reset --hard {origin_br}")
    steps.append("git clean -fd")
    media_worker = shell_quote(_RUST_MEDIA_HOST_WORKER)
    cloud_worker = shell_quote(_RUST_CLOUD_HOST_WORKER)
    cloud_message = shell_quote(
        "Missing executable CI-built Rust cloud binary at "
        f"{_RUST_CLOUD_HOST_WORKER}. Download and extract the GitHub Actions "
        "artifact yoyopod-rust-device-arm64-<sha> "
        "for this exact commit before Pi validation; do not build Rust binaries on the Pi."
    )
    steps.append(f"test -x {cloud_worker} || (echo {cloud_message} >&2 && exit 1)")
    media_message = shell_quote(
        "Missing executable CI-built Rust media binary at "
        f"{_RUST_MEDIA_HOST_WORKER}. Download and extract the GitHub Actions "
        "artifact yoyopod-rust-device-arm64-<sha> "
        "for this exact commit before Pi validation; do not build Rust binaries on the Pi."
    )
    steps.append(f"test -x {media_worker} || (echo {media_message} >&2 && exit 1)")
    runtime_worker = shell_quote(_RUST_RUNTIME_WORKER)
    runtime_message = shell_quote(
        "Missing executable CI-built Rust runtime binary at "
        f"{_RUST_RUNTIME_WORKER}. Download and extract the GitHub Actions "
        "artifact yoyopod-rust-device-arm64-<sha> "
        "for this exact commit before Pi validation; do not build Rust binaries on the Pi."
    )
    ui_worker = shell_quote(_RUST_UI_HOST_WORKER)
    ui_message = shell_quote(
        "Missing executable CI-built Rust UI binary at "
        f"{_RUST_UI_HOST_WORKER}. Download and extract the GitHub Actions "
        "artifact yoyopod-rust-device-arm64-<sha> "
        "for this exact commit before Pi validation; do not build Rust binaries on the Pi."
    )
    steps.append(f"test -x {runtime_worker} || (echo {runtime_message} >&2 && exit 1)")
    steps.append(f"test -x {ui_worker} || (echo {ui_message} >&2 && exit 1)")
    validate_deploy_cmd = checkout_module_command(venv_relpath, "pi", "validate", "deploy")
    smoke_cmd = checkout_module_command(venv_relpath, "pi", "validate", "smoke")
    steps.extend([validate_deploy_cmd, smoke_cmd])
    if with_cloud_voice:
        steps.append(checkout_module_command(venv_relpath, "pi", "validate", "cloud-voice"))
    if with_voip or with_voip_call_soak:
        voip_worker = shell_quote(_RUST_VOIP_HOST_WORKER)
        voip_message = shell_quote(
            "Missing executable CI-built Rust VoIP host binary. Download and extract the "
            "GitHub Actions artifact yoyopod-rust-device-arm64-<sha> for this exact "
            "commit before VoIP validation; do not build Rust binaries on the Pi."
        )
        steps.append(f"test -x {voip_worker} || (echo {voip_message} >&2 && exit 1)")
    if with_voip:
        steps.append(checkout_module_command(venv_relpath, "pi", "validate", "voip"))
    if with_voip_call_soak:
        steps.append(
            checkout_module_command(
                venv_relpath,
                "pi",
                "validate",
                "voip",
                "--soak",
                "call",
                "--soak-target",
                voip_soak_target,
                "--soak-seconds",
                str(voip_soak_seconds),
            )
        )
    steps.append(checkout_module_command(venv_relpath, "pi", "validate", "stability"))
    if with_lvgl_soak:
        steps.append(checkout_module_command(venv_relpath, "pi", "validate", "lvgl"))
    if with_navigation:
        steps.append(checkout_module_command(venv_relpath, "pi", "validate", "navigation"))
    if with_rust_ui_host or with_rust_ui_poc:
        steps.append(
            checkout_module_command(
                venv_relpath,
                "pi",
                "rust-ui-host",
                "--worker",
                _RUST_UI_HOST_WORKER,
            )
        )
    return " && ".join(steps)


@app.command()
def preflight(verbose: bool = typer.Option(False, "--verbose")) -> None:
    """Run host-side preflight checks (dirty tree + quality gate) before any remote work."""
    configure_logging(verbose)
    for label, argv in _build_preflight_steps():
        rc = run_local(argv, label)
        if rc != 0:
            raise typer.Exit(rc)


@app.command()
def validate(
    ctx: typer.Context,
    sha: str = typer.Option(
        "",
        "--sha",
        help="Pin validation to a specific commit on the target branch (must be an ancestor of origin/<branch>).",
    ),
    with_voip: bool = typer.Option(False, "--with-voip"),
    with_cloud_voice: bool = typer.Option(
        False,
        "--with-cloud-voice",
        help="Also validate cloud STT/TTS worker boundaries on the target.",
    ),
    with_lvgl_soak: bool = typer.Option(False, "--with-lvgl-soak"),
    with_navigation: bool = typer.Option(False, "--with-navigation"),
    with_voip_call_soak: bool = typer.Option(
        False,
        "--with-voip-call-soak",
        help="Run a real outbound VoIP call soak on the target after quick validation stages.",
    ),
    voip_soak_target: str = typer.Option(
        "",
        "--voip-soak-target",
        help="SIP URI to call when --with-voip-call-soak is enabled.",
    ),
    voip_soak_seconds: float = typer.Option(
        300.0,
        "--voip-soak-seconds",
        help="Seconds to hold the call connected during --with-voip-call-soak.",
    ),
    with_rust_ui_host: bool = typer.Option(
        False,
        "--with-rust-ui-host",
        help="Run the Rust UI host using a preinstalled CI artifact.",
    ),
    with_rust_ui_poc: bool = typer.Option(
        False,
        "--with-rust-ui-poc",
        help="Compatibility alias for --with-rust-ui-host.",
    ),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Run staged Pi validation. Pass --with-* to add optional stages."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    if with_voip_call_soak and not voip_soak_target.strip():
        typer.echo("--voip-soak-target is required with --with-voip-call-soak", err=True)
        raise typer.Exit(1)
    _require_local_revision_ready(conn.branch, sha)
    pi = load_pi_paths()
    cmd = _build_validate(
        branch=conn.branch,
        venv_relpath=pi.venv,
        sha=sha,
        with_voip=with_voip,
        with_cloud_voice=with_cloud_voice,
        with_lvgl_soak=with_lvgl_soak,
        with_navigation=with_navigation,
        with_voip_call_soak=with_voip_call_soak,
        voip_soak_target=voip_soak_target,
        voip_soak_seconds=voip_soak_seconds,
        with_rust_ui_host=with_rust_ui_host,
        with_rust_ui_poc=with_rust_ui_poc,
    )
    raise typer.Exit(run_remote(conn, cmd, tty=True))
