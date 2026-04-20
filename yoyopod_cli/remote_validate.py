"""Remote validate + preflight — run Pi validation stages over SSH.

Absorbs previous `remote lvgl-soak` as `--with-lvgl-soak`,
previous `remote navigation-soak` as `--with-navigation`.
"""

from __future__ import annotations

import typer

from yoyopod_cli.common import configure_logging
from yoyopod_cli.remote_shared import build_remote_app, pi_conn
from yoyopod_cli.remote_transport import run_local, run_remote, validate_config

app = build_remote_app("validate_app", "Validate commit + health on the Pi.")


def _build_preflight_steps() -> list[tuple[str, list[str]]]:
    """Preflight steps as (label, argv) tuples. Run them sequentially; exit on first failure."""
    return [
        ("git diff clean", ["git", "diff", "--quiet"]),
        ("git diff staged", ["git", "diff", "--cached", "--quiet"]),
        ("quality gate", ["uv", "run", "python", "scripts/quality.py", "ci"]),
    ]


def _build_validate(
    *,
    with_music: bool,
    with_voip: bool,
    with_lvgl_soak: bool,
    with_navigation: bool,
) -> str:
    """Shell that runs staged validation on the Pi."""
    steps = [
        "yoyopod pi validate deploy",
        "yoyopod pi validate smoke",
    ]
    if with_music:
        steps.append("yoyopod pi validate music")
    if with_voip:
        steps.append("yoyopod pi validate voip")
    steps.append("yoyopod pi validate stability")
    if with_lvgl_soak:
        steps.append("yoyopod pi validate lvgl")
    if with_navigation:
        steps.append("yoyopod pi validate navigation")
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
    with_music: bool = typer.Option(False, "--with-music"),
    with_voip: bool = typer.Option(False, "--with-voip"),
    with_lvgl_soak: bool = typer.Option(False, "--with-lvgl-soak"),
    with_navigation: bool = typer.Option(False, "--with-navigation"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Run staged Pi validation. Pass --with-* to add optional stages."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    cmd = _build_validate(
        with_music=with_music,
        with_voip=with_voip,
        with_lvgl_soak=with_lvgl_soak,
        with_navigation=with_navigation,
    )
    raise typer.Exit(run_remote(conn, cmd, tty=True))
