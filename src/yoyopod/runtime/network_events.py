"""Network-domain EventBus handlers for the runtime layer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yoyopod.events import (
    NetworkGpsFixEvent,
    NetworkGpsNoFixEvent,
    NetworkPppDownEvent,
    NetworkPppUpEvent,
    NetworkSignalUpdateEvent,
)

if TYPE_CHECKING:
    from yoyopod.app import YoyoPodApp


class NetworkEventHandler:
    """Own app-facing network event handlers."""

    def __init__(self, app: "YoyoPodApp") -> None:
        self.app = app

    def cellular_connection_type(self) -> str:
        """Return a best-effort cellular connection type for degraded status chrome."""

        if self.app.network_manager is None or not self.app.network_manager.config.enabled:
            return "none"

        from yoyopod.network.models import ModemPhase

        state = self.app.network_manager.modem_state
        if state.phase == ModemPhase.OFF:
            return "none"
        return "4g"

    def sync_network_context_from_manager(self) -> None:
        """Refresh AppContext network state from the current modem snapshot."""

        if self.app.context is None or self.app.network_manager is None:
            return

        state = self.app.network_manager.modem_state
        signal_bars = state.signal.bars if state.signal is not None else 0
        self.app.context.update_network_status(
            network_enabled=self.app.network_manager.config.enabled,
            signal_bars=signal_bars,
            connection_type=self.cellular_connection_type(),
            connected=self.app.network_manager.is_online,
            gps_has_fix=state.gps is not None,
        )

    def handle_network_ppp_up(self, event: NetworkPppUpEvent) -> None:
        """Refresh network connectivity state when PPP comes online."""

        if self.app.cloud_manager is not None:
            self.app.cloud_manager.note_network_change(connected=True)
        if self.app.network_manager is not None:
            self.sync_network_context_from_manager()
            return
        if self.app.context is not None:
            self.app.context.update_network_status(
                network_enabled=True,
                connected=True,
                connection_type=event.connection_type,
            )

    def handle_network_signal_update(self, event: NetworkSignalUpdateEvent) -> None:
        """Refresh signal bars when the modem reports new telemetry."""

        if self.app.network_manager is not None:
            self.sync_network_context_from_manager()
            return
        if self.app.context is not None:
            connection_type = self.app.context.network.connection_type
            if connection_type == "none":
                connection_type = "4g"
            self.app.context.update_network_status(
                network_enabled=True,
                signal_bars=event.bars,
                connection_type=connection_type,
            )

    def handle_network_gps_fix(self, event: NetworkGpsFixEvent) -> None:
        """Update GPS fix state in AppContext."""

        if self.app.network_manager is not None:
            self.sync_network_context_from_manager()
            return
        if self.app.context is not None:
            connection_type = self.app.context.network.connection_type
            if connection_type == "none":
                connection_type = "4g"
            self.app.context.update_network_status(
                network_enabled=True,
                connection_type=connection_type,
                gps_has_fix=True,
            )

    def handle_network_gps_no_fix(self, _event: NetworkGpsNoFixEvent) -> None:
        """Clear GPS fix state when a query completes without coordinates."""

        if self.app.network_manager is not None:
            self.sync_network_context_from_manager()
            return
        if self.app.context is not None:
            self.app.context.update_network_status(gps_has_fix=False)

    def handle_network_ppp_down(self, _event: NetworkPppDownEvent) -> None:
        """Reset network state in AppContext when PPP drops."""

        if self.app.cloud_manager is not None:
            self.app.cloud_manager.note_network_change(connected=False)
        if self.app.network_manager is not None:
            self.sync_network_context_from_manager()
            return
        if self.app.context is not None:
            self.app.context.update_network_status(
                network_enabled=True,
                connected=False,
                gps_has_fix=False,
            )
