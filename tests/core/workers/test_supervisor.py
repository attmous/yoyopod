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


def test_supervisor_stops_one_worker_domain(tmp_path: Path) -> None:
    worker = _write_worker(
        tmp_path,
        """
import sys
for line in sys.stdin:
    if '"type":"worker.stop"' in line or '"type": "worker.stop"' in line:
        break
""".strip(),
    )
    bus = Bus()
    scheduler = MainThreadScheduler()
    events: list[WorkerDomainStateChangedEvent] = []
    bus.subscribe(WorkerDomainStateChangedEvent, events.append)
    supervisor = WorkerSupervisor(scheduler=scheduler, bus=bus)
    supervisor.register(
        "ui",
        WorkerProcessConfig(name="ui", argv=[sys.executable, "-u", str(worker)]),
    )

    assert supervisor.start("ui")
    supervisor.stop("ui", grace_seconds=0.1)
    bus.drain()

    assert supervisor.snapshot()["ui"]["state"] == "stopped"
    assert events[-1] == WorkerDomainStateChangedEvent(
        domain="ui",
        state="stopped",
        reason="stop",
    )


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


def test_supervisor_sends_untracked_command_without_request_deadline() -> None:
    bus = Bus()
    scheduler = MainThreadScheduler()
    sent_commands: list[dict[str, object]] = []
    supervisor = WorkerSupervisor(scheduler=scheduler, bus=bus)
    supervisor.register("ui", WorkerProcessConfig(name="ui", argv=["unused"]))
    slot = supervisor._workers["ui"]
    slot.runtime = cast(
        object,
        SimpleNamespace(
            running=True,
            drain_messages=lambda limit=None: [],
            send_command=lambda **kwargs: sent_commands.append(kwargs) or True,
        ),
    )
    slot.state = "running"

    assert supervisor.send_command(
        "ui",
        type="ui.runtime_snapshot",
        payload={"app_state": "hub"},
    )

    assert sent_commands == [
        {
            "type": "ui.runtime_snapshot",
            "payload": {"app_state": "hub"},
            "request_id": None,
            "timestamp_ms": 0,
            "deadline_ms": 0,
        }
    ]
    assert slot.request_deadlines == {}


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
    sent_commands: list[dict[str, object]] = []
    bus.subscribe(WorkerMessageReceivedEvent, message_events.append)
    supervisor = WorkerSupervisor(scheduler=scheduler, bus=bus)
    supervisor.register("voice", WorkerProcessConfig(name="voice", argv=["unused"]))
    runtime = cast(
        object,
        SimpleNamespace(
            running=True,
            drain_messages=lambda limit=None: [],
            send_command=lambda **kwargs: sent_commands.append(kwargs) or True,
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
    retry_attempt = cast(
        int,
        cast(dict[str, object], sent_commands[-1])["payload"][
            supervisor._REQUEST_ATTEMPT_PAYLOAD_KEY
        ],
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
                    payload={
                        "text": "retry ok",
                        supervisor._REQUEST_ATTEMPT_PAYLOAD_KEY: retry_attempt,
                    },
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


def test_supervisor_accepts_retry_reply_without_private_attempt_marker() -> None:
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
            drain_messages=lambda limit=None: [],
            send_command=lambda **kwargs: sent_commands.append(kwargs) or True,
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
    assert "req-retry" not in slot.request_deadlines
    assert "req-retry" not in slot.request_attempts


def test_supervisor_ignores_late_cancel_ack_after_retry_reuses_request_id() -> None:
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
            drain_messages=lambda limit=None: [],
            send_command=lambda **kwargs: sent_commands.append(kwargs) or True,
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
    retry_attempt = cast(
        int,
        cast(dict[str, object], sent_commands[-1])["payload"][
            supervisor._REQUEST_ATTEMPT_PAYLOAD_KEY
        ],
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
                    payload={
                        "cancelled": True,
                        supervisor._REQUEST_ATTEMPT_PAYLOAD_KEY: retry_attempt - 1,
                    },
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


def test_supervisor_ignores_late_non_cancel_result_after_retry_reuses_request_id() -> None:
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
            drain_messages=lambda limit=None: [],
            send_command=lambda **kwargs: sent_commands.append(kwargs) or True,
        ),
    )
    slot = supervisor._workers["voice"]
    slot.runtime = runtime
    slot.state = "running"

    assert supervisor.send_request(
        "voice",
        type="voice.transcribe",
        payload={"path": "/tmp/first.wav"},
        request_id="req-retry",
        timeout_seconds=10.0,
    )
    first_attempt = cast(
        int,
        cast(dict[str, object], sent_commands[-1])["payload"][
            supervisor._REQUEST_ATTEMPT_PAYLOAD_KEY
        ],
    )
    slot.request_deadlines["req-retry"] = 1.0

    supervisor.poll(monotonic_now=2.0)

    assert supervisor.send_request(
        "voice",
        type="voice.transcribe",
        payload={"path": "/tmp/retry.wav"},
        request_id="req-retry",
        timeout_seconds=10.0,
    )
    retry_attempt = cast(
        int,
        cast(dict[str, object], sent_commands[-1])["payload"][
            supervisor._REQUEST_ATTEMPT_PAYLOAD_KEY
        ],
    )
    retry_deadline = slot.request_deadlines["req-retry"]
    assert retry_attempt == first_attempt + 1
    slot.runtime = cast(
        object,
        SimpleNamespace(
            running=True,
            drain_messages=lambda limit=None: [
                make_envelope(
                    kind="result",
                    type="voice.transcribe",
                    request_id="req-retry",
                    payload={
                        "text": "late stale result",
                        supervisor._REQUEST_ATTEMPT_PAYLOAD_KEY: first_attempt,
                    },
                )
            ],
            send_command=lambda **kwargs: sent_commands.append(kwargs) or True,
        ),
    )

    supervisor.poll(monotonic_now=2.1)
    bus.drain()

    assert message_events == []
    assert slot.request_deadlines["req-retry"] == pytest.approx(retry_deadline)
    assert len(slot.request_deadlines) == 1


def test_supervisor_retries_expired_request_before_poll_without_accepting_old_attempt() -> None:
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
            drain_messages=lambda limit=None: [],
            send_command=lambda **kwargs: sent_commands.append(kwargs) or True,
        ),
    )
    slot = supervisor._workers["voice"]
    slot.runtime = runtime
    slot.state = "running"

    assert supervisor.send_request(
        "voice",
        type="voice.transcribe",
        payload={"path": "/tmp/first.wav"},
        request_id="req-retry",
        timeout_seconds=10.0,
    )
    first_attempt = cast(
        int,
        cast(dict[str, object], sent_commands[-1])["payload"][
            supervisor._REQUEST_ATTEMPT_PAYLOAD_KEY
        ],
    )
    slot.request_deadlines["req-retry"] = time.monotonic() - 1.0

    assert supervisor.send_request(
        "voice",
        type="voice.transcribe",
        payload={"path": "/tmp/retry.wav"},
        request_id="req-retry",
        timeout_seconds=10.0,
    )
    retry_attempt = cast(
        int,
        cast(dict[str, object], sent_commands[-1])["payload"][
            supervisor._REQUEST_ATTEMPT_PAYLOAD_KEY
        ],
    )
    retry_deadline = slot.request_deadlines["req-retry"]
    assert retry_attempt == first_attempt + 1
    assert sent_commands[-2]["type"] == "voice.cancel"

    slot.runtime = cast(
        object,
        SimpleNamespace(
            running=True,
            drain_messages=lambda limit=None: [
                make_envelope(
                    kind="result",
                    type="voice.transcribe",
                    request_id="req-retry",
                    payload={
                        "text": "late stale result",
                        supervisor._REQUEST_ATTEMPT_PAYLOAD_KEY: first_attempt,
                    },
                )
            ],
            send_command=lambda **kwargs: sent_commands.append(kwargs) or True,
        ),
    )

    supervisor.poll(monotonic_now=time.monotonic())
    bus.drain()

    assert message_events == []
    assert slot.request_deadlines["req-retry"] == pytest.approx(retry_deadline)
    assert len(slot.request_deadlines) == 1


def test_supervisor_prunes_request_attempt_when_stale_timeout_retention_expires() -> None:
    bus = Bus()
    scheduler = MainThreadScheduler()
    supervisor = WorkerSupervisor(scheduler=scheduler, bus=bus)
    supervisor.register("voice", WorkerProcessConfig(name="voice", argv=["unused"]))
    slot = supervisor._workers["voice"]
    slot.runtime = cast(
        object,
        SimpleNamespace(
            running=True,
            drain_messages=lambda limit=None: [],
            send_command=lambda **_kwargs: True,
        ),
    )
    slot.state = "running"
    slot.request_attempts["req-stale"] = 7
    slot.stale_request_ids["req-stale"] = 5.0

    supervisor.poll(monotonic_now=5.0)

    assert slot.stale_request_ids == {}
    assert slot.request_attempts == {}


def test_supervisor_keeps_request_tracking_for_non_terminal_worker_event() -> None:
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
                    kind="event",
                    type="voice.progress",
                    request_id="req-progress",
                    payload={"state": "streaming"},
                )
            ],
            send_command=lambda **_kwargs: True,
        ),
    )
    slot.state = "running"
    slot.request_deadlines["req-progress"] = 10.0
    slot.request_attempts["req-progress"] = 1

    supervisor.poll(monotonic_now=1.0)
    bus.drain()

    assert message_events == [
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="event",
            type="voice.progress",
            request_id="req-progress",
            payload={"state": "streaming"},
        )
    ]
    assert slot.request_deadlines["req-progress"] == pytest.approx(10.0)
    assert slot.request_attempts["req-progress"] == 1


def test_supervisor_delivers_active_cancel_ack_for_explicit_cancel_request() -> None:
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
                    type="voice.cancelled",
                    request_id="req-cancel",
                    payload={"cancelled": True},
                )
            ],
            send_command=lambda **_kwargs: True,
        ),
    )
    slot.state = "running"

    assert supervisor.send_request(
        "voice",
        type="voice.cancel",
        payload={"request_id": "req-target"},
        request_id="req-cancel",
        timeout_seconds=10.0,
    )

    supervisor.poll(monotonic_now=1.0)
    bus.drain()

    assert message_events == [
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="result",
            type="voice.cancelled",
            request_id="req-cancel",
            payload={"cancelled": True},
        )
    ]
    assert "req-cancel" not in slot.request_deadlines
    assert "req-cancel" not in slot.request_attempts


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


def test_supervisor_redistributes_unused_poll_budget_from_idle_domains() -> None:
    bus = Bus()
    scheduler = MainThreadScheduler()
    message_events: list[WorkerMessageReceivedEvent] = []
    bus.subscribe(WorkerMessageReceivedEvent, message_events.append)
    supervisor = WorkerSupervisor(
        scheduler=scheduler,
        bus=bus,
        max_messages_per_poll=8,
    )
    supervisor.register("voice", WorkerProcessConfig(name="voice", argv=["unused"]))
    supervisor.register("network", WorkerProcessConfig(name="network", argv=["unused"]))
    supervisor.register("cloud", WorkerProcessConfig(name="cloud", argv=["unused"]))

    voice_messages = [
        make_envelope(
            kind="event",
            type="voice.event",
            request_id=None,
            payload={"index": index},
        )
        for index in range(5)
    ]
    drain_limits: list[int | None] = []

    def make_runtime(messages: list[WorkerEnvelope], *, record_limits: bool = False) -> object:
        def drain_messages(limit: int | None = None) -> list[WorkerEnvelope]:
            if record_limits:
                drain_limits.append(limit)
            count = len(messages) if limit is None else min(limit, len(messages))
            drained = messages[:count]
            del messages[:count]
            return drained

        return cast(
            object,
            SimpleNamespace(
                running=True,
                drain_messages=drain_messages,
                send_command=lambda **_kwargs: True,
            ),
        )

    supervisor._workers["voice"].runtime = make_runtime(voice_messages, record_limits=True)
    supervisor._workers["voice"].state = "running"
    supervisor._workers["network"].runtime = make_runtime([])
    supervisor._workers["network"].state = "running"
    supervisor._workers["cloud"].runtime = make_runtime([])
    supervisor._workers["cloud"].state = "running"

    assert supervisor.poll(monotonic_now=1.0) == 5
    bus.drain()

    assert [event.payload["index"] for event in message_events] == [0, 1, 2, 3, 4]
    assert voice_messages == []
    assert drain_limits == [2, 6]


def test_supervisor_rotates_message_budget_across_worker_domains() -> None:
    bus = Bus()
    scheduler = MainThreadScheduler()
    message_events: list[WorkerMessageReceivedEvent] = []
    bus.subscribe(WorkerMessageReceivedEvent, message_events.append)
    supervisor = WorkerSupervisor(
        scheduler=scheduler,
        bus=bus,
        max_messages_per_poll=1,
    )
    supervisor.register("voice", WorkerProcessConfig(name="voice", argv=["unused"]))
    supervisor.register("network", WorkerProcessConfig(name="network", argv=["unused"]))

    voice_messages = [
        make_envelope(
            kind="event",
            type="voice.event",
            request_id=None,
            payload={"domain": "voice", "index": 0},
        ),
        make_envelope(
            kind="event",
            type="voice.event",
            request_id=None,
            payload={"domain": "voice", "index": 1},
        ),
    ]
    network_messages = [
        make_envelope(
            kind="event",
            type="network.event",
            request_id=None,
            payload={"domain": "network", "index": 0},
        )
    ]

    def make_runtime(messages: list[WorkerEnvelope]) -> object:
        def drain_messages(limit: int | None = None) -> list[WorkerEnvelope]:
            count = len(messages) if limit is None else min(limit, len(messages))
            drained = messages[:count]
            del messages[:count]
            return drained

        return cast(
            object,
            SimpleNamespace(
                running=True,
                drain_messages=drain_messages,
                send_command=lambda **_kwargs: True,
            ),
        )

    supervisor._workers["voice"].runtime = make_runtime(voice_messages)
    supervisor._workers["voice"].state = "running"
    supervisor._workers["network"].runtime = make_runtime(network_messages)
    supervisor._workers["network"].state = "running"

    assert supervisor.poll(monotonic_now=1.0) == 1
    assert supervisor.poll(monotonic_now=2.0) == 1
    bus.drain()

    assert [(event.domain, event.payload["index"]) for event in message_events] == [
        ("voice", 0),
        ("network", 0),
    ]
    assert [message.payload["index"] for message in voice_messages] == [1]
    assert network_messages == []


def test_supervisor_checks_exit_and_restart_even_when_message_budget_is_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = Bus()
    scheduler = MainThreadScheduler()
    restart_calls: list[tuple[str, float]] = []
    supervisor = WorkerSupervisor(
        scheduler=scheduler,
        bus=bus,
        max_messages_per_poll=1,
    )
    supervisor.register("voice", WorkerProcessConfig(name="voice", argv=["unused"]))
    supervisor.register("network", WorkerProcessConfig(name="network", argv=["unused"]))
    supervisor.register("cloud", WorkerProcessConfig(name="cloud", argv=["unused"]))

    voice_messages = [
        make_envelope(
            kind="event",
            type="voice.event",
            request_id=None,
            payload={"index": 0},
        )
    ]
    voice_runtime = cast(
        object,
        SimpleNamespace(
            running=True,
            drain_messages=lambda limit=None: voice_messages[: (limit or len(voice_messages))],
            send_command=lambda **_kwargs: True,
            start=lambda: None,
            snapshot=lambda: SimpleNamespace(
                running=True,
                pid=1,
                received_messages=1,
                protocol_errors=0,
                dropped_messages=0,
                sent_messages=0,
                queued_sends=0,
                dropped_sends=0,
                send_failures=0,
            ),
        ),
    )
    exited_runtime = cast(
        object,
        SimpleNamespace(
            running=False,
            drain_messages=lambda limit=None: [],
            send_command=lambda **_kwargs: True,
            snapshot=lambda: SimpleNamespace(
                running=False,
                pid=2,
                received_messages=0,
                protocol_errors=0,
                dropped_messages=0,
                sent_messages=0,
                queued_sends=0,
                dropped_sends=0,
                send_failures=0,
            ),
        ),
    )
    degraded_runtime = cast(
        object,
        SimpleNamespace(
            running=True,
            drain_messages=lambda limit=None: [],
            send_command=lambda **_kwargs: True,
            snapshot=lambda: SimpleNamespace(
                running=True,
                pid=3,
                received_messages=0,
                protocol_errors=0,
                dropped_messages=0,
                sent_messages=0,
                queued_sends=0,
                dropped_sends=0,
                send_failures=0,
            ),
        ),
    )
    supervisor._workers["voice"].runtime = voice_runtime
    supervisor._workers["voice"].state = "running"
    supervisor._workers["network"].runtime = exited_runtime
    supervisor._workers["network"].state = "running"
    supervisor._workers["cloud"].runtime = degraded_runtime
    supervisor._workers["cloud"].state = "degraded"
    supervisor._workers["cloud"].next_restart_at = 1.0

    def restart_if_allowed(domain: str, slot, *, now: float) -> None:
        restart_calls.append((domain, now))

    monkeypatch.setattr(supervisor, "_restart_if_allowed", restart_if_allowed)

    supervisor.poll(monotonic_now=1.0)

    assert supervisor._workers["network"].state == "degraded"
    assert restart_calls == [("cloud", 1.0)]


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


def test_supervisor_initial_spawn_failure_retries_once_the_cwd_exists(tmp_path: Path) -> None:
    missing_dir = tmp_path / "missing-cwd"
    worker = _write_worker(
        tmp_path,
        """
import sys
for line in sys.stdin:
    pass
""".strip(),
    )
    bus = Bus()
    scheduler = MainThreadScheduler()
    events: list[WorkerDomainStateChangedEvent] = []
    bus.subscribe(WorkerDomainStateChangedEvent, events.append)
    supervisor = WorkerSupervisor(
        scheduler=scheduler,
        bus=bus,
        restart_backoff_seconds=0.01,
        max_restarts=1,
    )
    supervisor.register(
        "voice",
        WorkerProcessConfig(
            name="voice",
            argv=[sys.executable, "-u", str(worker)],
            cwd=str(missing_dir),
        ),
    )

    assert supervisor.start("voice") is False
    bus.drain()
    first_snapshot = supervisor.snapshot()["voice"]
    retry_at = cast(float, first_snapshot["next_restart_at"])

    assert first_snapshot["state"] == "degraded"
    assert first_snapshot["last_reason"] == "start_failed"
    assert retry_at > 0.0
    assert events[-1].state == "degraded"
    assert events[-1].reason == "start_failed"

    missing_dir.mkdir()
    try:
        _poll_until(
            lambda: (
                supervisor.poll() >= 0
                and bus.drain() >= 0
                and supervisor.snapshot()["voice"]["state"] == "running"
            ),
            timeout_seconds=1.0,
        )
        restarted_snapshot = supervisor.snapshot()["voice"]
    finally:
        supervisor.stop_all(grace_seconds=0.1)

    assert restarted_snapshot["state"] == "running"
    assert restarted_snapshot["restart_count"] == 1
    assert restarted_snapshot["next_restart_at"] == 0.0
    assert events[-1] == WorkerDomainStateChangedEvent(
        domain="voice",
        state="running",
        reason="started",
    )


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
