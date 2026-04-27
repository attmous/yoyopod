"""Tests for future wake detector seam."""

from __future__ import annotations

from yoyopod.integrations.voice.wake import NoopWakeDetector, WakeDetectionResult


def test_noop_wake_detector_is_button_gated_only() -> None:
    detector = NoopWakeDetector()

    assert detector.is_available() is False
    assert detector.start() is False
    assert detector.poll() == WakeDetectionResult(detected=False, phrase="")
    detector.stop()
