"""EventBus subscription wiring for ``YoyoPodApp`` runtime handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yoyopod.events import (
    NetworkGpsFixEvent,
    NetworkGpsNoFixEvent,
    NetworkPppDownEvent,
    NetworkPppUpEvent,
    NetworkSignalUpdateEvent,
    RecoveryAttemptCompletedEvent,
    ScreenChangedEvent,
    UserActivityEvent,
)
from yoyopod.power import (
    GracefulShutdownCancelled,
    GracefulShutdownRequested,
    LowBatteryWarningRaised,
)
from yoyopod.runtime.network_events import NetworkEventHandler
from yoyopod.runtime.power_events import PowerEventHandler
from yoyopod.runtime.voice_note_events import VoiceNoteEventHandler

if TYPE_CHECKING:
    from yoyopod.app import YoyoPodApp


class RuntimeEventWiring:
    """Own EventBus subscription wiring and domain-scoped event handlers."""

    def __init__(self, app: "YoyoPodApp") -> None:
        self.app = app
        self.voice_note_events = VoiceNoteEventHandler(app)
        self.power_events = PowerEventHandler(app)
        self.network_events = NetworkEventHandler(app)

    def register(self) -> None:
        """Subscribe app runtime handlers on the typed EventBus."""

        self.app.event_bus.subscribe(ScreenChangedEvent, self.handle_screen_changed_event)
        self.app.event_bus.subscribe(UserActivityEvent, self.handle_user_activity_event)
        self.app.event_bus.subscribe(
            RecoveryAttemptCompletedEvent,
            self.handle_recovery_attempt_completed_event,
        )
        self.app.event_bus.subscribe(
            LowBatteryWarningRaised,
            self.power_events.handle_low_battery_warning_event,
        )
        self.app.event_bus.subscribe(
            GracefulShutdownRequested,
            self.power_events.handle_graceful_shutdown_requested_event,
        )
        self.app.event_bus.subscribe(
            GracefulShutdownCancelled,
            self.power_events.handle_graceful_shutdown_cancelled_event,
        )
        self.app.event_bus.subscribe(NetworkPppUpEvent, self.network_events.handle_network_ppp_up)
        self.app.event_bus.subscribe(
            NetworkSignalUpdateEvent,
            self.network_events.handle_network_signal_update,
        )
        self.app.event_bus.subscribe(NetworkGpsFixEvent, self.network_events.handle_network_gps_fix)
        self.app.event_bus.subscribe(
            NetworkGpsNoFixEvent,
            self.network_events.handle_network_gps_no_fix,
        )
        self.app.event_bus.subscribe(
            NetworkPppDownEvent,
            self.network_events.handle_network_ppp_down,
        )

    def handle_screen_changed_event(self, event: ScreenChangedEvent) -> None:
        self.app.screen_power_service.handle_screen_changed_event(event)

    def handle_user_activity_event(self, event: UserActivityEvent) -> None:
        self.app.screen_power_service.handle_user_activity_event(event)

    def handle_recovery_attempt_completed_event(
        self,
        event: RecoveryAttemptCompletedEvent,
    ) -> None:
        self.app.recovery_service.handle_recovery_attempt_completed_event(event)
