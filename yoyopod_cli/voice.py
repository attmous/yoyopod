"""Voice diagnostics CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from yoyopod.integrations.voice.dictionary_validator import validate_voice_command_dictionary
from yoyopod.integrations.voice.trace import VoiceTraceStore
from yoyopod.integrations.voice.trace_analysis import analyze_voice_trace

app = typer.Typer(name="voice", help="Voice diagnostics and validation.", no_args_is_help=True)
dictionary_app = typer.Typer(
    name="dictionary",
    help="Validate voice command dictionaries.",
    no_args_is_help=True,
)
trace_app = typer.Typer(
    name="trace", help="Inspect local voice trace entries.", no_args_is_help=True
)
app.add_typer(dictionary_app, name="dictionary")
app.add_typer(trace_app, name="trace")


def _cell(value: Any, width: int = 28) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > width:
        if width <= 3:
            text = text[:width]
        else:
            text = f"{text[: width - 3]}..."
    return text.ljust(width)


def _row(payload: dict[str, Any]) -> str:
    target = payload.get("command_intent") or payload.get("route_name") or ""
    text = payload.get("transcript_normalized") or payload.get("assistant_body_preview") or ""
    values = (
        payload.get("completed_at", ""),
        payload.get("turn_id", ""),
        payload.get("source", ""),
        payload.get("mode", ""),
        payload.get("route_kind", ""),
        payload.get("outcome", ""),
        target,
        text,
    )
    return " ".join(_cell(value) for value in values).rstrip()


def _counts_text(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in counts.items())


def _configured_dictionary_path() -> Path:
    from yoyopod_cli.config import ConfigManager

    return Path(ConfigManager().get_voice_settings().assistant.command_dictionary_path)


def _configured_trace_path() -> Path:
    from yoyopod_cli.config import ConfigManager

    return Path(ConfigManager().get_voice_settings().trace.path)


@dictionary_app.command(name="validate")
def dictionary_validate(
    path: Path | None = typer.Option(None, "--path", help="Voice command dictionary YAML path."),
    strict: bool = typer.Option(False, "--strict", help="Treat warnings as failures."),
) -> None:
    """Validate a mutable voice command dictionary YAML file."""

    dictionary_path = path or _configured_dictionary_path()
    result = validate_voice_command_dictionary(dictionary_path, allow_missing=path is None)

    for issue in result.errors:
        typer.echo(f"ERROR {issue.location}: {issue.message}", err=True)
    for issue in result.warnings:
        typer.echo(f"WARN {issue.location}: {issue.message}")

    if result.has_errors or (strict and result.has_warnings):
        raise typer.Exit(1)

    suffix = ""
    if path is None and not dictionary_path.exists():
        suffix = " (built-ins only)"
    typer.echo(f"OK voice dictionary {dictionary_path}{suffix}")


@trace_app.command(name="last")
def trace_last(
    limit: int = typer.Option(5, "--limit", min=1, help="Number of recent trace entries to show."),
    path: Path | None = typer.Option(
        None,
        "--path",
        help="Path to the voice trace JSONL file.",
    ),
) -> None:
    """Show the most recent local voice trace entries."""

    trace_path = path or _configured_trace_path()
    rows = VoiceTraceStore(path=trace_path, max_turns=max(1, limit)).read_recent(limit=limit)
    rows = list(reversed(rows))
    if not rows:
        typer.echo(f"No voice trace entries at {trace_path}")
        return

    typer.echo(
        " ".join(
            _cell(value)
            for value in (
                "completed_at",
                "turn_id",
                "source",
                "mode",
                "route_kind",
                "outcome",
                "target",
                "text",
            )
        ).rstrip()
    )
    for payload in rows:
        typer.echo(_row(payload))


@trace_app.command(name="analyze")
def trace_analyze(
    limit: int = typer.Option(
        50, "--limit", min=1, help="Number of recent trace entries to analyze."
    ),
    path: Path | None = typer.Option(
        None,
        "--path",
        help="Path to the voice trace JSONL file.",
    ),
) -> None:
    """Summarize recent voice trace outcomes and failures."""

    trace_path = path or _configured_trace_path()
    rows = VoiceTraceStore(path=trace_path, max_turns=max(1, limit)).read_recent(limit=limit)
    if not rows:
        typer.echo(f"No voice trace entries at {trace_path}")
        return

    analysis = analyze_voice_trace(rows)
    typer.echo(f"Voice trace analysis: {analysis.total_turns} turn(s)")
    typer.echo(f"route_kind: {_counts_text(analysis.route_counts)}")
    typer.echo(f"outcome: {_counts_text(analysis.outcome_counts)}")
    typer.echo(f"commands: {_counts_text(analysis.command_counts)}")
    typer.echo(f"ask_fallback: {analysis.ask_fallback_turns}")

    if analysis.unknown_phrases:
        typer.echo("unknown phrases:")
        for phrase, count in analysis.unknown_phrases.items():
            typer.echo(f"- {phrase} ({count})")

    if analysis.recent_failures:
        typer.echo("recent failures:")
        for failure in analysis.recent_failures:
            typer.echo(
                f"- {failure.turn_id} {failure.route_kind}/{failure.outcome} {failure.text}".rstrip()
            )
