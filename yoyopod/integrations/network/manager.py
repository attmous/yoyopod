"""App-facing network manager owned by the canonical network integration seam."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from loguru import logger

from yoyopod.backends.network.modem import Sim7600Backend
from yoyopod.integrations.network.models import GpsCoordinate, ModemPhase, ModemState

if TYPE_CHECKING:
    from yoyopod.config import ConfigManager
    from yoyopod.config.models import NetworkConfig


class NetworkManager:
    """Coordinate modem backend access and publish events."""

    def __init__(
        self,
        config: "NetworkConfig",
        backend: object | None = None,
        event_publisher: Callable[[object], None] | None = None,
    ) -> None:
        self.config = config
        self.backend = backend or Sim7600Backend(config)
        self._event_publisher = event_publisher
        self._lifecycle_lock = threading.RLock()
        self._lifecycle_generation = 0

    @classmethod
    def from_config_manager(
        cls,
        config_manager: "ConfigManager",
        event_publisher: Callable[[object], None] | None = None,
    ) -> "NetworkManager":
        """Build a network manager from the typed network configuration."""

        config = config_manager.get_network_settings()
        return cls(config=config, event_publisher=event_publisher)

    def start(self) -> None:
        """Open modem, initialize, and start PPP."""

        self._start_flow()

    def start_background(
        self,
        *,
        on_failure: Callable[[Exception], None] | None = None,
    ) -> threading.Thread:
        """Run bring-up on a background thread for boot paths that must stay responsive."""

        def _run() -> None:
            try:
                self._start_flow()
            except Exception as exc:
                logger.error("Network manager background start failed: {}", exc)
                if on_failure is not None:
                    on_failure(exc)

        worker = threading.Thread(
            target=_run,
            daemon=True,
            name="network-start",
        )
        worker.start()
        return worker

    def _start_flow(self, *, expected_generation: int | None = None) -> bool:
        """Run the one-shot modem bring-up flow."""

        from yoyopod.integrations.network.events import (
            NetworkModemReadyEvent,
            NetworkPppUpEvent,
            NetworkRegisteredEvent,
            NetworkSignalUpdateEvent,
        )

        if not self.config.enabled:
            logger.info("Network module disabled")
            return False

        logger.info("Starting network manager")
        with self._lifecycle_lock:
            if expected_generation is None:
                expected_generation = self._lifecycle_generation
            elif expected_generation != self._lifecycle_generation:
                logger.info("Skipping network bring-up after concurrent lifecycle change")
                return False
            self.backend.open()
            self.backend.init_modem()
            state = self.backend.get_state()

        if not self._lifecycle_generation_matches(expected_generation):
            logger.info("Skipping network post-init after concurrent lifecycle change")
            return False

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

            if self._start_ppp(expected_generation=expected_generation):
                if not self._publish_if_lifecycle_matches(
                    NetworkPppUpEvent(connection_type="4g"),
                    expected_generation=expected_generation,
                ):
                    logger.info("Skipping PPP-up publish after concurrent lifecycle change")
                    return False
        else:
            logger.error("Modem init failed: {}", state.error)
        return True

    def stop(self) -> None:
        """Stop PPP and close the modem."""

        from yoyopod.integrations.network.events import NetworkPppDownEvent

        with self._lifecycle_lock:
            self._lifecycle_generation += 1
            logger.info("Stopping network manager")
            try:
                self.backend.close()
            except Exception as exc:
                logger.error("Error stopping network: {}", exc)
            self._publish(NetworkPppDownEvent(reason="shutdown"))

    def recover(self) -> bool:
        """Reset the modem backend and retry the full bring-up flow."""

        if not self.config.enabled:
            logger.info("Network module disabled")
            return False

        with self._lifecycle_lock:
            logger.info("Recovering network manager")
            expected_generation = self._lifecycle_generation
            try:
                self.backend.close()
            except Exception as exc:
                logger.debug("Ignoring network close error during recovery reset: {}", exc)

        try:
            if not self._start_flow(expected_generation=expected_generation):
                return False
        except Exception as exc:
            logger.error("Network recovery failed: {}", exc)
        return self.is_online

    @property
    def is_online(self) -> bool:
        """Return True when PPP is up."""

        with self._lifecycle_lock:
            backend_is_online = getattr(self.backend, "is_online", None)
            if callable(backend_is_online):
                return bool(backend_is_online())
            return self.backend.get_state().phase == ModemPhase.ONLINE

    @property
    def modem_state(self) -> ModemState:
        """Return the current modem state."""

        with self._lifecycle_lock:
            return self.backend.get_state()

    def query_gps(self) -> GpsCoordinate | None:
        """Query GPS coordinates (may briefly interrupt PPP)."""

        from yoyopod.integrations.location.events import (
            NetworkGpsFixEvent,
            NetworkGpsNoFixEvent,
        )

        with self._lifecycle_lock:
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

    def _start_ppp(self, *, expected_generation: int | None = None) -> bool:
        """Spawn PPP under lifecycle lock, then wait for the link without blocking shutdown."""

        wait_for_ppp_link = getattr(self.backend, "wait_for_ppp_link", None)
        with self._lifecycle_lock:
            if (
                expected_generation is not None
                and expected_generation != self._lifecycle_generation
            ):
                logger.info("Skipping PPP start after concurrent lifecycle change")
                return False
            if wait_for_ppp_link is None:
                return bool(self.backend.start_ppp())

            if not self.backend.start_ppp(wait_for_link=False):
                return False

        return bool(wait_for_ppp_link(timeout=self.config.ppp_timeout))

    def _lifecycle_generation_matches(self, expected_generation: int) -> bool:
        """Return True when no concurrent stop has invalidated the current bring-up."""

        with self._lifecycle_lock:
            return expected_generation == self._lifecycle_generation

    def _publish_if_lifecycle_matches(
        self,
        event: object,
        *,
        expected_generation: int,
    ) -> bool:
        """Publish only when no concurrent stop has invalidated the current lifecycle."""

        with self._lifecycle_lock:
            if expected_generation != self._lifecycle_generation:
                return False
            self._publish(event)
            return True

    def _publish(self, event: object) -> None:
        """Publish an event when a runtime publisher is available."""

        if self._event_publisher is not None:
            self._event_publisher(event)


__all__ = ["NetworkManager"]
