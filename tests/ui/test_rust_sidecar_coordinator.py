from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from yoyopod.core.events import WorkerMessageReceivedEvent
from yoyopod.integrations.call import AnswerCommand
from yoyopod.ui.rust_sidecar.coordinator import RustUiSidecarCoordinator


class _Supervisor:
    def __init__(self, *, messages: list[SimpleNamespace] | None = None) -> None:
        self.sent: list[tuple[str, str, dict[str, Any] | None, str | None]] = []
        self.registered: list[tuple[str, object]] = []
        self.started: list[str] = []
        self._messages = list(messages or [])

    def register(self, domain: str, config: object) -> None:
        self.registered.append((domain, config))

    def start(self, domain: str) -> bool:
        self.started.append(domain)
        return True

    def drain_worker_messages(self, domain: str) -> list[SimpleNamespace]:
        messages = self._messages
        self._messages = []
        return messages

    def snapshot(self) -> dict[str, dict[str, object]]:
        return {"ui": {"running": True}}

    def stop(self, domain: str, *, grace_seconds: float = 1.0) -> None:
        pass

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


class _Services:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    def call(self, domain: str, service: str, data: Any = None) -> None:
        self.calls.append((domain, service, data))


def test_coordinator_sends_runtime_snapshot_as_untracked_worker_command() -> None:
    supervisor = _Supervisor()
    app = SimpleNamespace(
        worker_supervisor=supervisor,
        context=None,
        app_state_runtime=None,
        people_directory=None,
    )
    coordinator = RustUiSidecarCoordinator(app, worker_domain="ui")

    assert coordinator.send_snapshot()

    assert supervisor.sent
    domain, message_type, payload, request_id = supervisor.sent[0]
    assert domain == "ui"
    assert message_type == "ui.runtime_snapshot"
    assert request_id is None
    assert payload is not None
    assert payload["hub"]["cards"][0]["title"] == "Listen"


def test_coordinator_registers_and_starts_worker() -> None:
    supervisor = _Supervisor(messages=[SimpleNamespace(kind="event", type="ui.ready", payload={})])
    app = SimpleNamespace(worker_supervisor=supervisor)
    coordinator = RustUiSidecarCoordinator(app, worker_domain="ui")

    assert coordinator.start_worker("yoyopod_rs/ui-host/build/yoyopod-ui-host")

    assert supervisor.started == ["ui"]
    domain, config = supervisor.registered[0]
    assert domain == "ui"
    assert getattr(config, "name") == "ui"
    assert getattr(config, "argv") == [
        "yoyopod_rs/ui-host/build/yoyopod-ui-host",
        "--hardware",
        "mock",
    ]


def test_coordinator_sends_tick_without_request_tracking() -> None:
    supervisor = _Supervisor()
    app = SimpleNamespace(worker_supervisor=supervisor)
    coordinator = RustUiSidecarCoordinator(app, worker_domain="ui")

    assert coordinator.send_tick(renderer="framebuffer")

    assert supervisor.sent == [("ui", "ui.tick", {"renderer": "framebuffer"}, None)]


def test_coordinator_dispatches_ui_intents_to_python_services() -> None:
    services = _Services()
    app = SimpleNamespace(services=services)
    coordinator = RustUiSidecarCoordinator(app, worker_domain="ui")

    coordinator.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="ui",
            kind="event",
            type="ui.intent",
            request_id=None,
            payload={
                "domain": "call",
                "action": "answer",
                "payload": {"source": "rust-ui"},
            },
        )
    )

    assert services.calls == [("call", "answer", AnswerCommand())]
