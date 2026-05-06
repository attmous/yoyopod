"""Tests for the repo-owned profiling helper script."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

PROFILE_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "profile.py"
PROFILE = runpy.run_path(str(PROFILE_SCRIPT))


def test_profile_targets_include_expected_targets() -> None:
    targets = PROFILE["TARGETS"]

    assert set(targets) >= {"scaffold-loop", "simulate-bootstrap", "simulate-loop"}


def test_default_output_path_uses_logs_profiles_directory() -> None:
    output = PROFILE["_resolve_output_path"](None, target="simulate-bootstrap", suffix=".prof")

    assert output.name == "simulate-bootstrap.prof"
    assert output.parent == PROFILE["PROFILE_OUTPUT_DIR"]


def test_build_pyperf_command_wraps_profile_runner() -> None:
    output_path = PROFILE["PROFILE_OUTPUT_DIR"] / "simulate-bootstrap.json"
    command = PROFILE["build_pyperf_command"](
        target="simulate-bootstrap",
        iterations=1,
        name="simulate-bootstrap",
        output=output_path,
        fast=True,
        rigorous=False,
        track_memory=True,
        quiet=True,
    )

    assert command[:4] == (sys.executable, "-m", "pyperf", "command")
    assert "--fast" in command
    assert "--track-memory" in command
    assert "--quiet" in command
    separator_index = command.index("--")
    assert command[separator_index:] == (
        "--",
        sys.executable,
        str(PROFILE_SCRIPT),
        "run",
        "simulate-bootstrap",
        "--iterations",
        "1",
    )
    assert str(output_path) in command
