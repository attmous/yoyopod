from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, cast

import pytest

from yoyopod.core.bus import Bus
from yoyopod.core.events import (
    WorkerDomainStateChangedEvent,
    WorkerMessageReceivedEvent,
)
from yoyopod.core.application import YoyoPodApp
from yoyopod.core.scheduler import MainThreadScheduler
from yoyopod.core.workers.process import WorkerProcessConfig
from yoyopod.core.workers.protocol import WorkerEnvelope, make_envelope
from yoyopod.core.workers.supervisor import WorkerSupervisor


def _write_worker(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "fake_worker.py"
    path.write_text(body, encoding="utf-8")
    return path


def _poll_until(assertion: Callable[[], bool], *, timeout_seconds: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if assertion():
            return
        time.sleep(0.01)
    assert assertion()


def test_supervisor_publishes_worker_messages_on_main_bus(tmp_path: Path) -> None:
    worker = _write_worker(
        tmp_path,
        """
import json
import sys
sys.stdout.write(json.dumps({
    "schema_version": 1,
    "kind": "event",
    "type": "fake.ready",
    "request_id": None,
    "timestamp_ms": 1,
    "deadline_ms": 0,
    "payload": {"ready": True},
}) + "\\n")
sys.stdout.flush()
for line in sys.stdin:
    pass
""".strip(),
    )
    bus = Bus()
    scheduler = MainThreadScheduler()
    state_events: list[WorkerDomainStateChangedEvent] = []
    message_events: list[WorkerMessageReceivedEvent] = []
    bus.subscribe(WorkerDomainStateChangedEvent, state_events.append)
    bus.subscribe(WorkerMessageReceivedEvent, message_events.append)
    supervisor = WorkerSupervisor(scheduler=scheduler, bus=bus)
    supervisor.register(
        "voice",
        WorkerProcessConfig(name="voice", argv=[sys.executable, "-u", str(worker)]),
    )

    supervisor.start("voice")
    try:
        _poll_until(lambda: supervisor.poll() >= 1)
        bus.drain()
        snapshot = supervisor.snapshot()
    finally:
        supervisor.stop_all(grace_seconds=0.1)

    assert state_events[0] == WorkerDomainStateChangedEvent(
        domain="voice",
        state="running",
        reason="started",
    )
    assert message_events == [
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="event",
            type="fake.ready",
            request_id=None,
            payload={"ready": True},
        )
    ]
    assert cast(int, snapshot["voice"]["received_messages"]) >= 1


def test_supervisor_marks_crashed_worker_degraded(tmp_path: Path) -> None:
    worker = _write_worker(tmp_path, "raise SystemExit(7)")
    bus = Bus()
    scheduler = MainThreadScheduler()
    events: list[WorkerDomainStateChangedEvent] = []
    bus.subscribe(WorkerDomainStateChangedEvent, events.append)
    supervisor = WorkerSupervisor(
        scheduler=scheduler,
        bus=bus,
        restart_backoff_seconds=60.0,
    )
    supervisor.register(
        "voice",
        WorkerProcessConfig(name="voice", argv=[sys.executable, "-u", str(worker)]),
    )

    supervisor.start("voice")
    supervisor.wait_until_exited("voice", timeout_seconds=2.0)
    supervisor.poll()
    bus.drain()

    assert supervisor.snapshot()["voice"]["state"] == "degraded"
    assert events[-1].domain == "voice"
    assert events[-1].state == "degraded"
    assert events[-1].reason == "process_exited"


def test_supervisor_request_timeout_sends_cancel(tmp_path: Path) -> None:
    worker = _write_worker(
        tmp_path,
        """
import json
import sys
for line in sys.stdin:
    msg = json.loads(line)
    if msg["type"] == "voice.cancel":
        sys.stdout.write(json.dumps({
            "schema_version": 1,
            "kind": "result",
            "type": "voice.cancelled",
            "request_id": msg.get("request_id"),
            "timestamp_ms": 1,
            "deadline_ms": 0,
            "payload": {"cancelled": True},
        }) + "\\n")
        sys.stdout.flush()
""".strip(),
    )
    bus = Bus()
    scheduler = MainThreadScheduler()
    message_events: list[WorkerMessageReceivedEvent] = []
    bus.subscribe(WorkerMessageReceivedEvent, message_events.append)
    supervisor = WorkerSupervisor(scheduler=scheduler, bus=bus)
    supervisor.register(
        "voice",
        WorkerProcessConfig(name="voice", argv=[sys.executable, "-u", str(worker)]),
    )

    supervisor.start("voice")
    try:
        assert supervisor.send_request(
            "voice",
            type="voice.transcribe",
            payload={"path": "/tmp/a.wav"},
            request_id="req-timeout",
            timeout_seconds=0.01,
        )
        time.sleep(0.05)
        supervisor.poll()
        _poll_until(lambda: supervisor.poll() >= 1)
        bus.drain()
        snapshot = supervisor.snapshot()
    finally:
        supervisor.stop_all(grace_seconds=0.1)

    assert snapshot["voice"]["request_timeouts"] == 1
    assert snapshot["voice"]["pending_requests"] == 0
    assert any(message.type == "voice.cancelled" for message in message_events)


def test_supervisor_drops_late_result_after_request_timeout() -> None:
    bus = Bus()
    scheduler = MainThreadScheduler()
    message_events: list[WorkerMessageReceivedEvent] = []
    bus.subscribe(WorkerMessageReceivedEvent, message_events.append)
    supervisor = WorkerSupervisor(scheduler=scheduler, bus=bus)
    supervisor.register("voice", WorkerProcessConfig(name="voice", argv=["unused"]))
    runtime = cast(
        object,
        SimpleNamespace(
            running=True,
            drain_messages=lambda limit=None: [],
            send_command=lambda **_kwargs: False,
        ),
    )
    slot = supervisor._workers["voice"]
    slot.runtime = runtime
    slot.state = "running"
    slot.request_deadlines["req-timeout"] = 1.0

    supervisor.poll(monotonic_now=2.0)
    runtime = cast(
        object,
        SimpleNamespace(
            running=True,
            drain_messages=lambda limit=None: [
                make_envelope(
                    kind="result",
                    type="voice.transcribe",
                    request_id="req-timeout",
                    payload={"text": "late"},
                )
            ],
            send_command=lambda **_kwargs: False,
        ),
    )
    slot.runtime = runtime
    supervisor.poll(monotonic_now=2.1)
    bus.drain()

    assert message_events == []


def test_supervisor_drops_stale_cancelled_payload_without_cancel_ack_type() -> None:
    bus = Bus()
    scheduler = MainThreadScheduler()
    message_events: list[WorkerMessageReceivedEvent] = []
    bus.subscribe(WorkerMessageReceivedEvent, message_events.append)
    supervisor = WorkerSupervisor(scheduler=scheduler, bus=bus)
    supervisor.register("voice", WorkerProcessConfig(name="voice", argv=["unused"]))
    slot = supervisor._workers["voice"]
    slot.runtime = cast(
        object,
        SimpleNamespace(
            running=True,
            drain_messages=lambda limit=None: [
                make_envelope(
                    kind="result",
                    type="voice.transcribe",
                    request_id="req-timeout",
                    payload={"cancelled": True, "text": "late"},
                )
            ],
            send_command=lambda **_kwargs: False,
        ),
    )
    slot.state = "running"
    slot.stale_request_ids["req-timeout"] = 30.0

    supervisor.poll(monotonic_now=2.0)
    bus.drain()

    assert message_events == []


def test_supervisor_expires_request_before_processing_late_result_in_same_poll() -> None:
    bus = Bus()
    scheduler = MainThreadScheduler()
    message_events: list[WorkerMessageReceivedEvent] = []
    sent_commands: list[dict[str, object]] = []
    bus.subscribe(WorkerMessageReceivedEvent, message_events.append)
    supervisor = WorkerSupervisor(scheduler=scheduler, bus=bus)
    supervisor.register("voice", WorkerProcessConfig(name="voice", argv=["unused"]))
    runtime = cast(
        object,
        SimpleNamespace(
            running=True,
            drain_messages=lambda limit=None: [
                make_envelope(
                    kind="result",
                    type="voice.transcribe",
                    request_id="req-late",
                    payload={"text": "late"},
                )
            ],
            send_command=lambda **kwargs: sent_commands.append(kwargs) is None or True,
        ),
    )
    slot = supervisor._workers["voice"]
    slot.runtime = runtime
    slot.state = "running"
    slot.request_deadlines["req-late"] = 1.0

    supervisor.poll(monotonic_now=2.0)
    bus.drain()

    assert message_events == []
    assert slot.request_timeouts == 1
    assert sent_commands[0]["type"] == "voice.cancel"


def test_supervisor_accepts_retry_with_same_request_id_after_timeout() -> None:
    bus = Bus()
    scheduler = MainThreadScheduler()
    message_events: list[WorkerMessageReceivedEvent] = []
    bus.subscribe(WorkerMessageReceivedEvent, message_events.append)
    supervisor = WorkerSupervisor(scheduler=scheduler, bus=bus)
    supervisor.register("voice", WorkerProcessConfig(name="voice", argv=["unused"]))
    runtime = cast(
        object,
        SimpleNamespace(
            running=True,
            drain_messages=lambda limit=None: [],
            send_command=lambda **_kwargs: True,
        ),
    )
    slot = supervisor._workers["voice"]
    slot.runtime = runtime
    slot.state = "running"
    slot.request_deadlines["req-retry"] = 1.0

    supervisor.poll(monotonic_now=2.0)

    assert supervisor.send_request(
        "voice",
        type="voice.transcribe",
        payload={"path": "/tmp/retry.wav"},
        request_id="req-retry",
        timeout_seconds=10.0,
    )
    slot.runtime = cast(
        object,
        SimpleNamespace(
            running=True,
            drain_messages=lambda limit=None: [
                make_envelope(
                    kind="result",
                    type="voice.transcribe",
                    request_id="req-retry",
                    payload={"text": "retry ok"},
                )
            ],
            send_command=lambda **_kwargs: True,
        ),
    )
    supervisor.poll(monotonic_now=2.1)
    bus.drain()

    assert message_events == [
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="result",
            type="voice.transcribe",
            request_id="req-retry",
            payload={"text": "retry ok"},
        )
    ]
    assert slot.stale_request_ids == {}


def test_supervisor_ignores_late_cancel_ack_after_retry_reuses_request_id() -> None:
    bus = Bus()
    scheduler = MainThreadScheduler()
    message_events: list[WorkerMessageReceivedEvent] = []
    bus.subscribe(WorkerMessageReceivedEvent, message_events.append)
    supervisor = WorkerSupervisor(scheduler=scheduler, bus=bus)
    supervisor.register("voice", WorkerProcessConfig(name="voice", argv=["unused"]))
    runtime = cast(
        object,
        SimpleNamespace(
            running=True,
            drain_messages=lambda limit=None: [],
            send_command=lambda **_kwargs: True,
        ),
    )
    slot = supervisor._workers["voice"]
    slot.runtime = runtime
    slot.state = "running"
    slot.request_deadlines["req-retry"] = 1.0

    supervisor.poll(monotonic_now=2.0)
    assert supervisor.send_request(
        "voice",
        type="voice.transcribe",
        payload={"path": "/tmp/retry.wav"},
        request_id="req-retry",
        timeout_seconds=10.0,
    )
    retry_deadline = slot.request_deadlines["req-retry"]
    slot.runtime = cast(
        object,
        SimpleNamespace(
            running=True,
            drain_messages=lambda limit=None: [
                make_envelope(
                    kind="result",
                    type="voice.cancelled",
                    request_id="req-retry",
                    payload={"cancelled": True},
                )
            ],
            send_command=lambda **_kwargs: True,
        ),
    )

    supervisor.poll(monotonic_now=2.1)
    bus.drain()

    assert message_events == []
    assert slot.request_deadlines["req-retry"] == pytest.approx(retry_deadline)
    assert len(slot.request_deadlines) == 1


def test_supervisor_caps_published_worker_messages_per_poll() -> None:
    bus = Bus()
    scheduler = MainThreadScheduler()
    message_events: list[WorkerMessageReceivedEvent] = []
    drain_limits: list[int | None] = []
    bus.subscribe(WorkerMessageReceivedEvent, message_events.append)
    supervisor = WorkerSupervisor(
        scheduler=scheduler,
        bus=bus,
        max_messages_per_poll=2,
    )
    supervisor.register("voice", WorkerProcessConfig(name="voice", argv=["unused"]))
    worker_messages = [
        make_envelope(
            kind="event",
            type="voice.event",
            request_id=None,
            payload={"index": index},
        )
        for index in range(3)
    ]

    def drain_messages(limit: int | None = None) -> list[WorkerEnvelope]:
        drain_limits.append(limit)
        count = len(worker_messages) if limit is None else min(limit, len(worker_messages))
        drained = worker_messages[:count]
        del worker_messages[:count]
        return drained

    slot = supervisor._workers["voice"]
    slot.runtime = cast(
        object,
        SimpleNamespace(
            running=True,
            drain_messages=drain_messages,
            send_command=lambda **_kwargs: True,
        ),
    )
    slot.state = "running"

    assert supervisor.poll(monotonic_now=1.0) == 2
    bus.drain()

    assert drain_limits == [2]
    assert [event.payload["index"] for event in message_events] == [0, 1]
    assert [message.payload["index"] for message in worker_messages] == [2]


def test_supervisor_rejects_duplicate_start_without_replacing_runtime(tmp_path: Path) -> None:
    worker = _write_worker(
        tmp_path,
        """
import time
time.sleep(60)
""".strip(),
    )
    bus = Bus()
    scheduler = MainThreadScheduler()
    supervisor = WorkerSupervisor(scheduler=scheduler, bus=bus)
    supervisor.register(
        "voice",
        WorkerProcessConfig(name="voice", argv=[sys.executable, "-u", str(worker)]),
    )

    supervisor.start("voice")
    try:
        first_snapshot = supervisor.snapshot()["voice"]
        with pytest.raises(RuntimeError, match="already running"):
            supervisor.start("voice")
        second_snapshot = supervisor.snapshot()["voice"]
    finally:
        supervisor.stop_all(grace_seconds=0.1)

    assert first_snapshot["running"] is True
    assert second_snapshot["running"] is True
    assert second_snapshot["pid"] == first_snapshot["pid"]


def test_supervisor_restart_waits_for_backoff(tmp_path: Path) -> None:
    worker = _write_worker(tmp_path, "raise SystemExit(7)")
    bus = Bus()
    scheduler = MainThreadScheduler()
    events: list[WorkerDomainStateChangedEvent] = []
    bus.subscribe(WorkerDomainStateChangedEvent, events.append)
    supervisor = WorkerSupervisor(
        scheduler=scheduler,
        bus=bus,
        restart_backoff_seconds=5.0,
        max_restarts=1,
    )
    supervisor.register(
        "voice",
        WorkerProcessConfig(name="voice", argv=[sys.executable, "-u", str(worker)]),
    )

    supervisor.start("voice")
    supervisor.wait_until_exited("voice", timeout_seconds=2.0)
    supervisor.poll(monotonic_now=10.0)
    supervisor.poll(monotonic_now=14.9)
    bus.drain()
    snapshot = supervisor.snapshot()["voice"]

    assert snapshot["state"] == "degraded"
    assert snapshot["restart_count"] == 0
    assert snapshot["next_restart_at"] == 15.0
    assert [event.state for event in events].count("degraded") == 1


def test_supervisor_restarts_after_backoff_when_allowed(tmp_path: Path) -> None:
    worker = _write_worker(tmp_path, "raise SystemExit(7)")
    bus = Bus()
    scheduler = MainThreadScheduler()
    events: list[WorkerDomainStateChangedEvent] = []
    bus.subscribe(WorkerDomainStateChangedEvent, events.append)
    supervisor = WorkerSupervisor(
        scheduler=scheduler,
        bus=bus,
        restart_backoff_seconds=5.0,
        max_restarts=1,
    )
    supervisor.register(
        "voice",
        WorkerProcessConfig(name="voice", argv=[sys.executable, "-u", str(worker)]),
    )

    supervisor.start("voice")
    supervisor.wait_until_exited("voice", timeout_seconds=2.0)
    supervisor.poll(monotonic_now=10.0)
    supervisor.poll(monotonic_now=15.0)
    bus.drain()
    snapshot = supervisor.snapshot()["voice"]
    supervisor.stop_all(grace_seconds=0.1)

    assert snapshot["state"] == "running"
    assert snapshot["restart_count"] == 1
    assert snapshot["next_restart_at"] == 0.0
    assert events[-1].state == "running"
    assert events[-1].reason == "started"


def test_supervisor_disables_after_max_restarts(tmp_path: Path) -> None:
    worker = _write_worker(tmp_path, "raise SystemExit(7)")
    bus = Bus()
    scheduler = MainThreadScheduler()
    events: list[WorkerDomainStateChangedEvent] = []
    bus.subscribe(WorkerDomainStateChangedEvent, events.append)
    supervisor = WorkerSupervisor(
        scheduler=scheduler,
        bus=bus,
        restart_backoff_seconds=1.0,
        max_restarts=0,
    )
    supervisor.register(
        "voice",
        WorkerProcessConfig(name="voice", argv=[sys.executable, "-u", str(worker)]),
    )

    supervisor.start("voice")
    supervisor.wait_until_exited("voice", timeout_seconds=2.0)
    supervisor.poll(monotonic_now=10.0)
    supervisor.poll(monotonic_now=11.0)
    bus.drain()
    snapshot = supervisor.snapshot()["voice"]

    assert snapshot["state"] == "disabled"
    assert snapshot["last_reason"] == "max_restarts_exceeded"
    assert snapshot["restart_count"] == 0
    assert snapshot["next_restart_at"] == 0.0
    assert events[-1] == WorkerDomainStateChangedEvent(
        domain="voice",
        state="disabled",
        reason="max_restarts_exceeded",
    )


def test_supervisor_restart_spawn_failure_stays_contained(tmp_path: Path) -> None:
    worker_dir = tmp_path / "worker-cwd"
    worker_dir.mkdir()
    worker = _write_worker(tmp_path, "raise SystemExit(7)")
    bus = Bus()
    scheduler = MainThreadScheduler()
    events: list[WorkerDomainStateChangedEvent] = []
    bus.subscribe(WorkerDomainStateChangedEvent, events.append)
    supervisor = WorkerSupervisor(
        scheduler=scheduler,
        bus=bus,
        restart_backoff_seconds=1.0,
        max_restarts=1,
    )
    supervisor.register(
        "voice",
        WorkerProcessConfig(
            name="voice",
            argv=[sys.executable, "-u", str(worker)],
            cwd=str(worker_dir),
        ),
    )

    supervisor.start("voice")
    supervisor.wait_until_exited("voice", timeout_seconds=2.0)
    worker_dir.rmdir()
    supervisor.poll(monotonic_now=10.0)
    supervisor.poll(monotonic_now=11.0)
    bus.drain()
    snapshot = supervisor.snapshot()["voice"]

    assert snapshot["state"] == "degraded"
    assert snapshot["last_reason"] == "restart_failed"
    assert snapshot["restart_count"] == 1
    assert snapshot["next_restart_at"] == 0.0
    assert events[-1].state == "degraded"
    assert events[-1].reason == "restart_failed"


def test_supervisor_initial_spawn_failure_stays_contained(tmp_path: Path) -> None:
    missing_dir = tmp_path / "missing-cwd"
    bus = Bus()
    scheduler = MainThreadScheduler()
    events: list[WorkerDomainStateChangedEvent] = []
    bus.subscribe(WorkerDomainStateChangedEvent, events.append)
    supervisor = WorkerSupervisor(scheduler=scheduler, bus=bus)
    supervisor.register(
        "voice",
        WorkerProcessConfig(
            name="voice",
            argv=[sys.executable, "-u", "-c", "print('unused')"],
            cwd=str(missing_dir),
        ),
    )

    assert supervisor.start("voice") is False
    bus.drain()
    snapshot = supervisor.snapshot()["voice"]

    assert snapshot["state"] == "degraded"
    assert snapshot["last_reason"] == "start_failed"
    assert events[-1].state == "degraded"
    assert events[-1].reason == "start_failed"


def test_app_owns_worker_supervisor() -> None:
    app = YoyoPodApp()

    assert isinstance(app.worker_supervisor, WorkerSupervisor)
    assert app.get_status


def test_status_includes_worker_snapshot() -> None:
    app = YoyoPodApp()
    app.app_state_runtime = type("State", (), {"get_state_name": lambda self: "idle"})()
    app.call_interruption_policy = type(
        "Policy",
        (),
        {"music_interrupted_by_call": False},
    )()

    status = app.get_status()

    assert status["workers"] == {}
