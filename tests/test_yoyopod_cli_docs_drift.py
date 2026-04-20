"""Verify yoyopod_cli/COMMANDS.md is in sync with the Typer tree."""
from __future__ import annotations

from yoyopod_cli._docgen import generate_commands_md
from yoyopod_cli.main import app
from yoyopod_cli.paths import HOST


def test_commands_md_is_up_to_date() -> None:
    committed = (HOST.repo_root / "yoyopod_cli" / "COMMANDS.md").read_text(encoding="utf-8")
    regenerated = generate_commands_md(app)
    assert committed == regenerated, (
        "yoyopod_cli/COMMANDS.md is out of date. "
        "Run `uv run yoyopod dev docs` and commit."
    )
