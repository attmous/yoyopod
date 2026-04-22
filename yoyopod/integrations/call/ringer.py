"""Canonical incoming-call ring-tone process helper."""

from __future__ import annotations

import subprocess

from loguru import logger


class CallRinger:
    """Manage the speaker-test subprocess used for the incoming ring tone."""

    def __init__(self) -> None:
        self._ringing_process: subprocess.Popen | None = None

    def start(self, config_manager: object | None = None) -> None:
        """Start playing the ring tone for an incoming call."""

        self.stop()

        try:
            self._ringing_process = subprocess.Popen(
                self.build_command(config_manager),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.debug("Ring tone started")
        except Exception as exc:
            logger.warning("Failed to start ring tone: {}", exc)

    def stop(self) -> None:
        """Stop playing the ring tone if a process is active."""

        if self._ringing_process is None:
            return

        try:
            self._ringing_process.terminate()
            self._ringing_process.wait(timeout=1.0)
            logger.debug("Ring tone stopped")
        except Exception as exc:
            logger.warning("Failed to stop ring tone: {}", exc)
        finally:
            self._ringing_process = None

    @staticmethod
    def build_command(config_manager: object | None = None) -> list[str]:
        """Build the canonical speaker-test command for the ring tone."""

        ring_output_device = None
        speaker_test_path = "speaker-test"
        if config_manager is not None:
            get_ring_output_device = getattr(config_manager, "get_ring_output_device", None)
            get_speaker_test_path = getattr(config_manager, "get_speaker_test_path", None)
            if callable(get_ring_output_device):
                ring_output_device = get_ring_output_device()
            if callable(get_speaker_test_path):
                speaker_test_path = get_speaker_test_path()

        command = [
            speaker_test_path,
            "-t",
            "sine",
            "-f",
            "800",
        ]
        if ring_output_device:
            command.extend(["-D", ring_output_device])
        return command


__all__ = ["CallRinger"]
