"""Remote validate + preflight — run Pi validation stages over SSH.

Absorbs previous `remote lvgl-soak` as `--with-lvgl-soak`,
previous `remote navigation-soak` as `--with-navigation`.
"""

from __future__ import annotations

import typer

from yoyopod_cli.common import configure_logging
from yoyopod_cli.remote_shared import build_remote_app, pi_conn
from yoyopod_cli.remote_transport import (
    run_local,
    run_local_capture,
    run_remote,
    shell_quote,
    validate_config,
)

app = build_remote_app("validate_app", "Validate commit + health on the Pi.")


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
    sha: str = "",
    with_music: bool,
    with_voip: bool,
    with_power: bool = False,
    with_rtc: bool = False,
    with_lvgl_soak: bool,
    with_navigation: bool,
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
    smoke_cmd = "uv run yoyopod pi validate smoke"
    if with_power:
        smoke_cmd += " --with-power"
    if with_rtc:
        smoke_cmd += " --with-rtc"
    steps.extend(["uv run yoyopod pi validate deploy", smoke_cmd])
    if with_music:
        steps.append("uv run yoyopod pi validate music")
    if with_voip:
        steps.append("uv run yoyopod pi validate voip")
    steps.append("uv run yoyopod pi validate stability")
    if with_lvgl_soak:
        steps.append("uv run yoyopod pi validate lvgl")
    if with_navigation:
        steps.append("uv run yoyopod pi validate navigation")
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
    with_music: bool = typer.Option(False, "--with-music"),
    with_voip: bool = typer.Option(False, "--with-voip"),
    with_power: bool = typer.Option(False, "--with-power"),
    with_rtc: bool = typer.Option(False, "--with-rtc"),
    with_lvgl_soak: bool = typer.Option(False, "--with-lvgl-soak"),
    with_navigation: bool = typer.Option(False, "--with-navigation"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Run staged Pi validation. Pass --with-* to add optional stages."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    _require_local_revision_ready(conn.branch, sha)
    cmd = _build_validate(
        branch=conn.branch,
        sha=sha,
        with_music=with_music,
        with_voip=with_voip,
        with_power=with_power,
        with_rtc=with_rtc,
        with_lvgl_soak=with_lvgl_soak,
        with_navigation=with_navigation,
    )
    raise typer.Exit(run_remote(conn, cmd, tty=True))
