"""Recovery and manager-health supervision helpers."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from loguru import logger

from yoyopod.core import RecoveryAttemptCompletedEvent
from yoyopod.runtime.models import RecoveryState

if TYPE_CHECKING:
    from yoyopod.app import YoyoPodApp


class RecoverySupervisor:
    """Supervise recoverable VoIP/music backends."""

    _RECOVERY_MAX_DELAY_SECONDS = 30.0

    def __init__(self, app: "YoyoPodApp") -> None:
        self.app = app
        self.voip_recovery = RecoveryState()
        self.music_recovery = RecoveryState()
        self.network_recovery = RecoveryState()

    def handle_recovery_attempt_completed_event(
        self,
        event: RecoveryAttemptCompletedEvent,
    ) -> None:
        """Finalize background recovery attempts on the coordinator thread."""
        if event.manager == "music":
            self.music_recovery.in_flight = False
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
                self.music_recovery,
                event.recovered,
                event.recovery_now,
            )
            return

        if event.manager != "network":
            return

        self.network_recovery.in_flight = False
        if self.app._stopping:
            return

        if self.app.network_manager is not None:
            self.app.event_wiring.network_events.sync_network_context_from_manager()
            if self.app.cloud_manager is not None:
                self.app.cloud_manager.note_network_change(
                    connected=self.app.network_manager.is_online
                )

        self.finalize_recovery_attempt(
            "Network",
            self.network_recovery,
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
        self.attempt_network_recovery(recovery_now)

    def attempt_voip_recovery(self, recovery_now: float) -> None:
        """Restart the VoIP backend when it is not running."""
        if self.app.voip_manager is None:
            return

        if self.app.voip_manager.running:
            self.voip_recovery.reset()
            return

        if recovery_now < self.voip_recovery.next_attempt_at:
            return

        logger.info("Attempting VoIP recovery")
        self.finalize_recovery_attempt(
            "VoIP",
            self.voip_recovery,
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
            self.music_recovery.reset()
            return

        if self.music_recovery.in_flight:
            return

        if recovery_now < self.music_recovery.next_attempt_at:
            return

        logger.info("Attempting music backend recovery")
        self.music_recovery.in_flight = True
        self.start_music_recovery_worker(recovery_now)

    def attempt_network_recovery(self, recovery_now: float) -> None:
        """Reinitialize the modem when cellular registration or PPP is down."""

        if (
            self.app.simulate
            or self.app.network_manager is None
            or not self.app.network_manager.config.enabled
        ):
            return

        if self.network_recovery.in_flight:
            return

        if self.app.network_manager.is_online:
            self.network_recovery.reset()
            return

        if recovery_now < self.network_recovery.next_attempt_at:
            return

        logger.info("Attempting network recovery")
        self.network_recovery.in_flight = True
        self.start_network_recovery_worker(recovery_now)

    def start_music_recovery_worker(self, recovery_now: float) -> None:
        """Launch the non-blocking music recovery attempt worker."""
        worker = threading.Thread(
            target=self.run_music_recovery_attempt,
            args=(recovery_now,),
            daemon=True,
            name="music-recovery",
        )
        worker.start()

    def start_network_recovery_worker(self, recovery_now: float) -> None:
        """Launch the non-blocking network recovery attempt worker."""

        worker = threading.Thread(
            target=self.run_network_recovery_attempt,
            args=(recovery_now,),
            daemon=True,
            name="network-recovery",
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

    def run_network_recovery_attempt(self, recovery_now: float) -> None:
        """Run one modem reinitialization attempt off the coordinator thread."""

        recovered = False
        if not self.app._stopping and self.app.network_manager is not None:
            recovered = self.app.network_manager.recover()

        self.app.event_bus.publish(
            RecoveryAttemptCompletedEvent(
                manager="network",
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
            self._RECOVERY_MAX_DELAY_SECONDS,
        )
