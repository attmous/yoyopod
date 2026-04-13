"""App-facing network manager facade."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from yoyopy.network.backend import Sim7600Backend
from yoyopy.network.models import GpsCoordinate, ModemPhase, ModemState

if TYPE_CHECKING:
    from yoyopy.config import ConfigManager
    from yoyopy.config.models import AppNetworkConfig
    from yoyopy.event_bus import EventBus


class NetworkManager:
    """Coordinate modem backend access and publish events."""

    def __init__(
        self,
        config: "AppNetworkConfig",
        backend: object | None = None,
        event_bus: "EventBus | None" = None,
    ) -> None:
        self.config = config
        self.backend = backend or Sim7600Backend(config)
        self.event_bus = event_bus

    @classmethod
    def from_config_manager(
        cls, config_manager: "ConfigManager", event_bus: "EventBus | None" = None
    ) -> "NetworkManager":
        """Build a network manager from the typed app configuration."""
        config = config_manager.get_app_settings().network
        return cls(config=config, event_bus=event_bus)

    def start(self) -> None:
        """Open modem, initialize, and start PPP."""
        from yoyopy.events import (
            NetworkModemReadyEvent,
            NetworkPppUpEvent,
            NetworkRegisteredEvent,
            NetworkSignalUpdateEvent,
        )

        if not self.config.enabled:
            logger.info("Network module disabled")
            return

        logger.info("Starting network manager")
        self.backend.open()
        self.backend.init_modem()

        state = self.backend.get_state()
        if state.phase == ModemPhase.REGISTERED:
            self._publish(
                NetworkModemReadyEvent(
                    carrier=state.carrier,
                    network_type=state.network_type,
                )
            )
            self._publish(
                NetworkRegisteredEvent(
                    carrier=state.carrier,
                    network_type=state.network_type,
                )
            )
            if state.signal:
                self._publish(
                    NetworkSignalUpdateEvent(
                        bars=state.signal.bars,
                        csq=state.signal.csq,
                    )
                )

            if self.config.gps_enabled:
                try:
                    self.query_gps()
                except Exception as exc:
                    logger.debug("Initial GPS query failed: {}", exc)

            if self.backend.start_ppp():
                self._publish(NetworkPppUpEvent(connection_type="4g"))
        else:
            logger.error("Modem init failed: {}", state.error)

    def stop(self) -> None:
        """Stop PPP and close the modem."""
        from yoyopy.events import NetworkPppDownEvent

        logger.info("Stopping network manager")
        try:
            self.backend.close()
        except Exception as exc:
            logger.error("Error stopping network: {}", exc)
        self._publish(NetworkPppDownEvent(reason="shutdown"))

    @property
    def is_online(self) -> bool:
        """Return True when PPP is up."""
        return self.backend.get_state().phase == ModemPhase.ONLINE

    @property
    def modem_state(self) -> ModemState:
        """Return the current modem state."""
        return self.backend.get_state()

    def query_gps(self) -> GpsCoordinate | None:
        """Query GPS coordinates (may briefly interrupt PPP)."""
        from yoyopy.events import NetworkGpsFixEvent, NetworkGpsNoFixEvent

        coord = self.backend.query_gps()
        if coord is not None:
            self._publish(
                NetworkGpsFixEvent(
                    lat=coord.lat,
                    lng=coord.lng,
                    altitude=coord.altitude,
                    speed=coord.speed,
                )
            )
        else:
            self._publish(NetworkGpsNoFixEvent(reason="no_fix"))
        return coord

    def _publish(self, event: object) -> None:
        """Publish an event if the bus is available."""
        if self.event_bus is not None:
            self.event_bus.publish(event)
