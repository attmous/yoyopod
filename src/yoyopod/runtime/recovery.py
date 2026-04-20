"""Recovery and manager-health supervision helpers."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from loguru import logger

from yoyopod.core import RecoveryAttemptCompletedEvent

if TYPE_CHECKING:
    from yoyopod.app import YoyoPodApp
    from yoyopod.runtime.models import RecoveryState


class RecoverySupervisor:
    """Supervise recoverable VoIP/music backends."""

    def __init__(self, app: "YoyoPodApp") -> None:
        self.app = app

    def handle_recovery_attempt_completed_event(
        self,
        event: RecoveryAttemptCompletedEvent,
    ) -> None:
        """Finalize background recovery attempts on the coordinator thread."""
        if event.manager != "music":
            return

        self.app._music_recovery.in_flight = False
        if self.app._stopping:
            return

        if event.recovered and self.app.music_backend:
            if hasattr(self.app.music_backend, "polling") and not getattr(
                self.app.music_backend,
                "polling",
            ):
                start_polling = getattr(self.app.music_backend, "start_polling", None)
                if start_polling is not None:
                    start_polling()

        self.finalize_recovery_attempt(
            "Music",
            self.app._music_recovery,
            event.recovered,
            event.recovery_now,
        )

    def attempt_manager_recovery(self, now: float | None = None) -> None:
        """Try to recover VoIP and music when they become unavailable."""
        if self.app._stopping:
            return

        recovery_now = time.monotonic() if now is None else now
        self.attempt_voip_recovery(recovery_now)
        self.attempt_music_recovery(recovery_now)

    def attempt_voip_recovery(self, recovery_now: float) -> None:
        """Restart the VoIP backend when it is not running."""
        if self.app.voip_manager is None:
            return

        if self.app.voip_manager.running:
            self.app._voip_recovery.reset()
            return

        if recovery_now < self.app._voip_recovery.next_attempt_at:
            return

        logger.info("Attempting VoIP recovery")
        self.finalize_recovery_attempt(
            "VoIP",
            self.app._voip_recovery,
            self.app.voip_manager.start(),
            recovery_now,
        )

    def start_music_backend(self) -> bool:
        """Start the current music backend using the available lifecycle API."""
        if self.app.music_backend is None:
            return False

        start = getattr(self.app.music_backend, "start", None)
        if start is not None:
            return bool(start())

        connect = getattr(self.app.music_backend, "connect", None)
        if connect is not None:
            return bool(connect())

        return False

    def attempt_music_recovery(self, recovery_now: float) -> None:
        """Reconnect the music backend when it becomes unavailable."""
        if self.app.music_backend is None:
            return

        if self.app.music_backend.is_connected:
            self.app._music_recovery.reset()
            return

        if self.app._music_recovery.in_flight:
            return

        if recovery_now < self.app._music_recovery.next_attempt_at:
            return

        logger.info("Attempting music backend recovery")
        self.app._music_recovery.in_flight = True
        self.start_music_recovery_worker(recovery_now)

    def start_music_recovery_worker(self, recovery_now: float) -> None:
        """Launch the non-blocking music recovery attempt worker."""
        worker = threading.Thread(
            target=self.run_music_recovery_attempt,
            args=(recovery_now,),
            daemon=True,
            name="music-recovery",
        )
        worker.start()

    def run_music_recovery_attempt(self, recovery_now: float) -> None:
        """Run a single music recovery attempt off the coordinator thread."""
        recovered = False
        if not self.app._stopping and self.app.music_backend is not None:
            recovered = self.start_music_backend()

        self.app.event_bus.publish(
            RecoveryAttemptCompletedEvent(
                manager="music",
                recovered=recovered,
                recovery_now=recovery_now,
            )
        )

    def finalize_recovery_attempt(
        self,
        label: str,
        state: "RecoveryState",
        recovered: bool,
        recovery_now: float,
    ) -> None:
        """Update reconnect backoff after a recovery attempt."""
        if recovered:
            logger.info(f"{label} recovery succeeded")
            state.reset()
            return

        retry_in = state.delay_seconds
        logger.warning(f"{label} recovery failed, retrying in {retry_in:.0f}s")
        state.next_attempt_at = recovery_now + retry_in
        state.delay_seconds = min(
            state.delay_seconds * 2.0,
            self.app._RECOVERY_MAX_DELAY_SECONDS,
        )
