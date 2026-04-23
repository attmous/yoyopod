"""Shared CLI helpers (logging, repo root, config dir resolution)."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

from loguru import logger

REPO_ROOT = Path(__file__).resolve().parents[1]


def configure_logging(verbose: bool) -> None:
    """Configure loguru for CLI commands."""
    logger.remove()
    level = "DEBUG" if verbose else "INFO"
    logger.add(sys.stderr, level=level, format="{time:HH:mm:ss} | {level:<7} | {message}")


def resolve_config_dir(config_dir: str) -> Path:
    """Resolve a config directory relative to the repo root."""
    path = Path(config_dir)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def checkout_python_path(venv_path: str) -> str:
    """Return the checkout-local Python interpreter path for a POSIX virtualenv."""

    normalized = venv_path.rstrip("/")
    if normalized.endswith("/bin/python"):
        return normalized
    if normalized.endswith("/bin/activate"):
        return f"{normalized.removesuffix('/activate')}/python"
    return f"{normalized}/bin/python"


def shell_quote_preserving_home(value: str) -> str:
    """Shell-quote a value while preserving leading ~/ expansion via $HOME."""

    if value == "~":
        return '"$HOME"'
    if value.startswith("~/"):
        suffix = (
            value[2:]
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("$", "\\$")
            .replace("`", "\\`")
        )
        return f'"$HOME/{suffix}"'
    return shlex.quote(value)


def shell_join_preserving_home(args: tuple[str, ...]) -> str:
    """Join shell arguments, preserving home-relative configured paths."""

    return " ".join(shell_quote_preserving_home(arg) for arg in args)


def checkout_module_command(venv_path: str, *args: str, module: str = "yoyopod_cli.main") -> str:
    """Build one shell-safe checkout-local ``python -m ...`` invocation."""

    python_path = shell_quote_preserving_home(checkout_python_path(venv_path))
    argv = " ".join(shlex.quote(arg) for arg in args)
    if argv:
        return f"{python_path} -m {module} {argv}"
    return f"{python_path} -m {module}"
