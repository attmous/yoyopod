"""Thin Python facade for the Rust-owned network host runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from yoyopod.core.events import WorkerDomainStateChangedEvent, WorkerMessageReceivedEvent
from yoyopod.core.workers import WorkerProcessConfig
from yoyopod.integrations.network.snapshot import RustNetworkSnapshot


class RustNetworkFacade:
    """Supervise the Rust worker and project its snapshot into AppContext."""

    def __init__(self, app: Any, *, worker_domain: str = "network") -> None:
        self.app = app
        self.worker_domain = worker_domain
        self._snapshot: RustNetworkSnapshot | None = None
        self._worker_state: str | None = None
        self._worker_reason: str = ""

    def start_worker(
        self,
        worker_path: str,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> bool:
        supervisor = getattr(self.app, "worker_supervisor", None)
        register = getattr(supervisor, "register", None)
        start = getattr(supervisor, "start", None)
        if not callable(register) or not callable(start):
            return False

        runtime_cwd = cwd or str(Path(__file__).resolve().parents[3])
        config_dir = str(getattr(self.app, "config_dir", "config"))
        try:
            register(
                self.worker_domain,
                WorkerProcessConfig(
                    name=self.worker_domain,
                    argv=[worker_path, "--config-dir", config_dir],
                    cwd=runtime_cwd,
                    env=env,
                ),
            )
        except ValueError:
            logger.debug("Network worker domain {} already registered", self.worker_domain)

        started = bool(start(self.worker_domain))
        if started and self._snapshot is None:
            self._clear_context()
        return started

    def stop(self, *, grace_seconds: float = 1.0) -> bool:
        supervisor = getattr(self.app, "worker_supervisor", None)
        send_command = getattr(supervisor, "send_command", None)
        stop = getattr(supervisor, "stop", None)
        sent = False
        if callable(send_command):
            sent = bool(
                send_command(
                    self.worker_domain,
                    type="network.shutdown",
                    payload={},
                )
            )
        if callable(stop):
            stop(self.worker_domain, grace_seconds=grace_seconds)
            return True
        return sent

    def snapshot(self) -> RustNetworkSnapshot | None:
        """Return the latest cached Rust snapshot, when available."""

        return self._snapshot

    def is_available(self) -> bool:
        """Return True when a worker snapshot is available."""

        return self._snapshot is not None and self._worker_state not in _UNAVAILABLE_WORKER_STATES

    def query_gps(self) -> bool:
        """Request one GPS refresh from the Rust worker."""

        return self._send_command("network.query_gps")

    def reset_modem(self) -> bool:
        """Request one modem reset from the Rust worker."""

        return self._send_command("network.reset_modem")

    def handle_worker_message(self, event: WorkerMessageReceivedEvent) -> None:
        if event.domain != self.worker_domain:
            return

        if event.type == "network.snapshot":
            self._apply_snapshot_payload(event.payload)
            return

        if event.type == "network.health":
            self._apply_snapshot_payload(event.payload)
            return

        if event.type == "network.error":
            code = str(event.payload.get("code", "") or "").strip()
            message = str(event.payload.get("message", "") or "").strip()
            logger.warning(
                "Rust network host error: code={} message={}",
                code or "unknown",
                message or "unknown",
            )

    def handle_worker_state_change(self, event: WorkerDomainStateChangedEvent) -> None:
        if event.domain != self.worker_domain:
            return
        previous_connected = self._projected_connected(self._snapshot)
        self._worker_state = event.state
        self._worker_reason = event.reason
        if self._snapshot is None:
            self._clear_context()
            return
        self._sync_context(self._snapshot)
        self._note_connected_edge(
            previous_connected=previous_connected,
            current_connected=self._projected_connected(self._snapshot),
        )

    def _send_command(self, message_type: str) -> bool:
        supervisor = getattr(self.app, "worker_supervisor", None)
        send_command = getattr(supervisor, "send_command", None)
        if not callable(send_command):
            return False
        return bool(
            send_command(
                self.worker_domain,
                type=message_type,
                payload={},
            )
        )

    def _apply_snapshot_payload(self, payload: dict[str, Any]) -> None:
        snapshot_payload = payload.get("snapshot", payload)
        if not isinstance(snapshot_payload, dict):
            return
        self._apply_snapshot(RustNetworkSnapshot.from_payload(snapshot_payload))

    def _apply_snapshot(self, snapshot: RustNetworkSnapshot) -> None:
        previous_connected = self._projected_connected(self._snapshot)
        self._snapshot = snapshot
        self._worker_state = "running"
        self._worker_reason = ""
        self._sync_context(snapshot)
        self._note_connected_edge(
            previous_connected=previous_connected,
            current_connected=self._projected_connected(snapshot),
        )

    def _sync_context(self, snapshot: RustNetworkSnapshot) -> None:
        context = getattr(self.app, "context", None)
        if context is None:
            return
        context.update_network_status(
            network_enabled=snapshot.enabled,
            signal_bars=snapshot.signal_bars,
            connection_type=snapshot.connection_type,
            connected=self._projected_connected(snapshot),
            gps_has_fix=self._projected_gps_has_fix(snapshot),
        )

    def _clear_context(self) -> None:
        context = getattr(self.app, "context", None)
        if context is None:
            return
        context.update_network_status(
            network_enabled=False,
            signal_bars=0,
            connection_type="none",
            connected=False,
            gps_has_fix=False,
        )

    def _projected_connected(self, snapshot: RustNetworkSnapshot | None) -> bool | None:
        if snapshot is None:
            return None
        if self._worker_state in _UNAVAILABLE_WORKER_STATES:
            return False
        return snapshot.connected

    def _projected_gps_has_fix(self, snapshot: RustNetworkSnapshot) -> bool:
        if self._worker_state in _UNAVAILABLE_WORKER_STATES:
            return False
        return snapshot.gps_has_fix

    def _note_connected_edge(
        self,
        *,
        previous_connected: bool | None,
        current_connected: bool | None,
    ) -> None:
        if (
            previous_connected is None
            or current_connected is None
            or previous_connected == current_connected
        ):
            return
        cloud_manager = getattr(self.app, "cloud_manager", None)
        note_network_change = getattr(cloud_manager, "note_network_change", None)
        if callable(note_network_change):
            note_network_change(connected=current_connected)


_UNAVAILABLE_WORKER_STATES = {"degraded", "disabled", "stopped"}


__all__ = ["RustNetworkFacade"]
