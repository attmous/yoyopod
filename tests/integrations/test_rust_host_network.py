"""Tests for the thin Python facade around the Rust network host."""

from __future__ import annotations

from dataclasses import asdict
from types import SimpleNamespace
from typing import Any

from yoyopod.core import AppContext
from yoyopod.core.events import WorkerMessageReceivedEvent
from yoyopod.integrations.network.rust_host import RustNetworkFacade
from yoyopod.integrations.network.snapshot import (
    RustNetworkGpsSnapshot,
    RustNetworkPppSnapshot,
    RustNetworkSignalSnapshot,
    RustNetworkSnapshot,
)


class _Supervisor:
    def __init__(self) -> None:
        self.registered: list[tuple[str, object]] = []
        self.started: list[str] = []
        self.stopped: list[tuple[str, float]] = []
        self.sent: list[tuple[str, str, dict[str, Any] | None, str | None]] = []

    def register(self, domain: str, config: object) -> None:
        self.registered.append((domain, config))

    def start(self, domain: str) -> bool:
        self.started.append(domain)
        return True

    def stop(self, domain: str, *, grace_seconds: float = 1.0) -> None:
        self.stopped.append((domain, grace_seconds))

    def send_command(
        self,
        domain: str,
        *,
        type: str,
        payload: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> bool:
        self.sent.append((domain, type, payload, request_id))
        return True


def _snapshot(*, connected: bool = False) -> RustNetworkSnapshot:
    return RustNetworkSnapshot(
        enabled=True,
        gps_enabled=True,
        config_dir="config/test-device",
        state="online" if connected else "registered",
        sim_ready=True,
        registered=True,
        carrier="Telekom.de",
        network_type="4G",
        signal=RustNetworkSignalSnapshot(csq=20, bars=3),
        ppp=RustNetworkPppSnapshot(
            up=connected,
            interface="ppp0",
            pid=1234 if connected else None,
            default_route_owned=connected,
            last_failure="",
        ),
        gps=RustNetworkGpsSnapshot(has_fix=False, last_query_result="idle"),
        recovering=False,
        retryable=True,
        reconnect_attempts=0,
        next_retry_at_ms=None,
        error_code="",
        error_message="",
        updated_at_ms=1,
    )


def test_facade_registers_worker_with_config_dir() -> None:
    supervisor = _Supervisor()
    app = SimpleNamespace(
        worker_supervisor=supervisor,
        config_dir="config/test-device",
        context=AppContext(),
    )
    facade = RustNetworkFacade(app, worker_domain="network")

    assert facade.start_worker("yoyopod_rs/network-host/build/yoyopod-network-host")

    assert supervisor.started == ["network"]
    domain, config = supervisor.registered[0]
    assert domain == "network"
    assert getattr(config, "argv") == [
        "yoyopod_rs/network-host/build/yoyopod-network-host",
        "--config-dir",
        "config/test-device",
    ]


def test_facade_sends_query_gps_without_request_tracking() -> None:
    supervisor = _Supervisor()
    app = SimpleNamespace(
        worker_supervisor=supervisor,
        context=AppContext(),
    )
    facade = RustNetworkFacade(app, worker_domain="network")

    assert facade.query_gps() is True
    assert supervisor.sent == [("network", "network.query_gps", {}, None)]


def test_facade_applies_health_result_snapshot_to_cache_and_context() -> None:
    supervisor = _Supervisor()
    app = SimpleNamespace(
        worker_supervisor=supervisor,
        context=AppContext(),
        cloud_manager=None,
    )
    facade = RustNetworkFacade(app, worker_domain="network")
    snapshot = _snapshot(connected=True)

    facade.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="network",
            kind="result",
            type="network.health",
            request_id="health-1",
            payload={"snapshot": asdict(snapshot)},
        )
    )

    assert facade.snapshot() == snapshot
    assert app.context.network.enabled is True
    assert app.context.network.connected is True
    assert app.context.network.connection_type == "4g"
    assert app.context.network.signal_strength == 3
