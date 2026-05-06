"""Future wake-word detector seam for YoYo voice activation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True, frozen=True)
class WakeDetectionResult:
    """Result returned by a wake detector poll."""

    detected: bool
    phrase: str = ""


class WakeDetector(Protocol):
    """Backend interface for future always-listening wake detection."""

    def is_available(self) -> bool:
        """Return True when this backend can run on the current device."""

    def start(self) -> bool:
        """Start wake detection."""

    def poll(self) -> WakeDetectionResult:
        """Return the latest wake detection state."""

    def stop(self) -> None:
        """Stop wake detection and release resources."""


class NoopWakeDetector:
    """Button-gated wake detector used until hardware wake listening ships."""

    def is_available(self) -> bool:
        return False

    def start(self) -> bool:
        return False

    def poll(self) -> WakeDetectionResult:
        return WakeDetectionResult(detected=False, phrase="")

    def stop(self) -> None:
        return None


__all__ = [
    "NoopWakeDetector",
    "WakeDetectionResult",
    "WakeDetector",
]
