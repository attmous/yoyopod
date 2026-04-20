"""Tests for the repo-owned quality command wrapper."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

QUALITY_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "quality.py"
QUALITY = runpy.run_path(str(QUALITY_SCRIPT))


def test_ci_steps_wrap_gate_plus_pytest() -> None:
    config = QUALITY["load_quality_config"]()

    gate_steps = QUALITY["build_gate_steps"](config)
    ci_steps = QUALITY["build_ci_steps"](config)

    assert ci_steps[:-1] == gate_steps
    assert ci_steps[-1].label == "pytest -q (CI test suite)"
    assert ci_steps[-1].command == (sys.executable, "-m", "pytest", "-q")


def test_parser_accepts_ci_command() -> None:
    parser = QUALITY["build_parser"]()

    args = parser.parse_args(["ci"])

    assert args.command == "ci"


def test_gate_steps_expand_directory_targets_into_python_files() -> None:
    config = QUALITY["load_quality_config"]()

    gate_steps = QUALITY["build_gate_steps"](config)
    black_steps = [step for step in gate_steps if step.label == "black --check (workflow surface)"]
    black_targets = [Path(step.command[-1]) for step in black_steps]

    assert black_targets
    assert Path("yoyopod_cli") not in black_targets
    assert Path("yoyopod_cli/main.py") in black_targets
    assert all(target.suffix == ".py" for target in black_targets)
