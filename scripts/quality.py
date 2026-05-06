#!/usr/bin/env python3
"""Repo-owned quality command runner used by both local workflow and CI."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"


@dataclass(frozen=True)
class QualityConfig:
    """Tracked quality target sets loaded from ``pyproject.toml``."""

    gate_format_paths: tuple[str, ...]
    gate_lint_paths: tuple[str, ...]
    gate_type_paths: tuple[str, ...]
    audit_format_paths: tuple[str, ...]
    audit_lint_paths: tuple[str, ...]
    audit_type_paths: tuple[str, ...]


@dataclass(frozen=True)
class QualityStep:
    """One executable quality command."""

    label: str
    command: tuple[str, ...]


def _load_pyproject() -> dict[str, Any]:
    with PYPROJECT_PATH.open("rb") as handle:
        payload = tomllib.load(handle)
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected a TOML mapping in {PYPROJECT_PATH}")
    return payload


def _load_string_list(section: dict[str, Any], key: str) -> tuple[str, ...]:
    raw_value = section.get(key)
    if not isinstance(raw_value, list) or not raw_value:
        raise SystemExit(f"Expected a non-empty string list for [tool.yoyopod_quality].{key}")

    normalized: list[str] = []
    for item in raw_value:
        if not isinstance(item, str) or not item.strip():
            raise SystemExit(
                f"Expected [tool.yoyopod_quality].{key} to contain only non-empty strings"
            )
        normalized.append(item.strip())
    return tuple(normalized)


def load_quality_config() -> QualityConfig:
    """Load the tracked quality target sets from ``pyproject.toml``."""

    payload = _load_pyproject()
    tool_section = payload.get("tool")
    if not isinstance(tool_section, dict):
        raise SystemExit(f"Missing [tool] section in {PYPROJECT_PATH}")

    quality_section = tool_section.get("yoyopod_quality")
    if not isinstance(quality_section, dict):
        raise SystemExit(f"Missing [tool.yoyopod_quality] section in {PYPROJECT_PATH}")

    return QualityConfig(
        gate_format_paths=_load_string_list(quality_section, "gate_format_paths"),
        gate_lint_paths=_load_string_list(quality_section, "gate_lint_paths"),
        gate_type_paths=_load_string_list(quality_section, "gate_type_paths"),
        audit_format_paths=_load_string_list(quality_section, "audit_format_paths"),
        audit_lint_paths=_load_string_list(quality_section, "audit_lint_paths"),
        audit_type_paths=_load_string_list(quality_section, "audit_type_paths"),
    )


def _python_module_command(module: str, *args: str) -> tuple[str, ...]:
    return (sys.executable, "-m", module, *args)


def _expand_python_paths(paths: tuple[str, ...]) -> tuple[str, ...]:
    """Expand tracked directory targets into stable Python file lists."""

    expanded_paths: list[str] = []
    for raw_path in paths:
        candidate = REPO_ROOT / raw_path
        if candidate.is_dir():
            expanded_paths.extend(
                str(path.relative_to(REPO_ROOT))
                for path in sorted(candidate.rglob("*.py"))
                if "__pycache__" not in path.parts
            )
            continue
        expanded_paths.append(raw_path)
    return tuple(expanded_paths)


def _build_black_steps(label: str, paths: tuple[str, ...]) -> tuple[QualityStep, ...]:
    """Run Black one tracked file at a time to keep gate progress bounded."""

    expanded_paths = _expand_python_paths(paths)
    return tuple(
        QualityStep(
            label=label,
            command=_python_module_command("black", "--check", path),
        )
        for path in expanded_paths
    )


def build_gate_steps(config: QualityConfig) -> tuple[QualityStep, ...]:
    """Build the staged, CI-gated workflow checks."""

    return (
        *_build_black_steps("black --check (workflow surface)", config.gate_format_paths),
        QualityStep(
            label="ruff check (workflow surface)",
            command=_python_module_command(
                "ruff",
                "check",
                *_expand_python_paths(config.gate_lint_paths),
            ),
        ),
        QualityStep(
            label="mypy (workflow surface)",
            command=_python_module_command(
                "mypy",
                *_expand_python_paths(config.gate_type_paths),
            ),
        ),
    )


def build_ci_steps(config: QualityConfig) -> tuple[QualityStep, ...]:
    """Build the local command that mirrors current CI expectations."""

    return build_gate_steps(config)


def build_audit_steps(config: QualityConfig) -> tuple[QualityStep, ...]:
    """Build the non-gating full-repo audit commands."""

    return (
        QualityStep(
            label="black --check (full repo audit)",
            command=_python_module_command("black", "--check", *config.audit_format_paths),
        ),
        QualityStep(
            label="ruff check (full repo audit)",
            command=_python_module_command("ruff", "check", *config.audit_lint_paths),
        ),
        QualityStep(
            label="mypy (full repo audit)",
            command=_python_module_command("mypy", *config.audit_type_paths),
        ),
    )


def run_steps(steps: tuple[QualityStep, ...]) -> int:
    """Run every step and return a non-zero exit code when any fail."""

    failures: list[tuple[str, int]] = []
    for step in steps:
        print("")
        print(f"[quality] step={step.label}")
        print(f"[quality] cmd={shlex.join(step.command)}")
        completed = subprocess.run(step.command, cwd=REPO_ROOT, check=False)
        if completed.returncode != 0:
            failures.append((step.label, completed.returncode))

    print("")
    if failures:
        print("[quality] result=failed")
        for label, return_code in failures:
            print(f"[quality] failed_step={label} exit_code={return_code}")
        return 1

    print("[quality] result=passed")
    return 0


def print_targets(config: QualityConfig) -> None:
    """Print the tracked gate and audit target sets."""

    sections = (
        ("gate_format_paths", config.gate_format_paths),
        ("gate_lint_paths", config.gate_lint_paths),
        ("gate_type_paths", config.gate_type_paths),
        ("audit_format_paths", config.audit_format_paths),
        ("audit_lint_paths", config.audit_lint_paths),
        ("audit_type_paths", config.audit_type_paths),
    )
    for name, values in sections:
        print(f"{name}:")
        for value in values:
            print(f"  - {value}")


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""

    parser = argparse.ArgumentParser(
        description="Run repo-owned quality commands for YoYoPod Core."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "ci",
        help="Run the local command that mirrors CI: staged quality gate.",
    )
    subparsers.add_parser("gate", help="Run the staged CI-gated workflow checks.")
    subparsers.add_parser("audit", help="Run the non-gating full-repo quality audit.")
    subparsers.add_parser("targets", help="Print the tracked gate and audit target sets.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""

    args = build_parser().parse_args(argv)
    config = load_quality_config()

    if args.command == "ci":
        return run_steps(build_ci_steps(config))
    if args.command == "gate":
        return run_steps(build_gate_steps(config))
    if args.command == "audit":
        return run_steps(build_audit_steps(config))
    if args.command == "targets":
        print_targets(config)
        return 0
    raise SystemExit(f"Unsupported quality command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
