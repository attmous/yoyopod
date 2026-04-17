"""Tests for pure Whisplay tuning-script helpers."""

from __future__ import annotations

import pytest

pytest.importorskip("typer")

from yoyopod.cli.pi.tune import apply_timing_overrides, summarize_timings


def test_apply_timing_overrides_updates_input_section() -> None:
    """Temporary CLI overrides should land in the input config only."""
    app_config = {
        "audio": {"music_dir": "/srv/music"},
        "input": {
            "whisplay_debounce_ms": 50,
            "whisplay_double_tap_ms": 300,
            "whisplay_long_hold_ms": 800,
        },
    }

    merged = apply_timing_overrides(
        app_config,
        debounce_ms=70,
        double_tap_ms=260,
        long_hold_ms=920,
    )

    assert merged["audio"]["music_dir"] == "/srv/music"
    assert merged["input"]["whisplay_debounce_ms"] == 70
    assert merged["input"]["whisplay_double_tap_ms"] == 260
    assert merged["input"]["whisplay_long_hold_ms"] == 920


def test_summarize_timings_formats_current_values() -> None:
    """Timing summary should expose the current debounce/double/hold values."""
    summary = summarize_timings(
        {
            "input": {
                "whisplay_debounce_ms": 60,
                "whisplay_double_tap_ms": 250,
                "whisplay_long_hold_ms": 900,
            }
        }
    )

    assert summary == "debounce=60ms, double=250ms, hold=900ms"
