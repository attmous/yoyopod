from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any, cast

from yoyopod.core.workers.process import WorkerProcessConfig, WorkerProcessRuntime


def _write_worker(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "fake_worker.py"
    path.write_text(body, encoding="utf-8")
    return path


class _BlockingStdin:
    def __init__(self) -> None:
        self.write_entered = threading.Event()
        self.release_write = threading.Event()

    def write(self, data: bytes) -> int:
        self.write_entered.set()
        self.release_write.wait(timeout=5.0)
        return len(data)

    def flush(self) -> None:
        return None


class _RecordingStdin:
    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        return len(data)

    def flush(self) -> None:
        return None


class _FakeProcess:
    pid = 1234

    def __init__(self, stdin: object | None = None) -> None:
        self.stdin = _BlockingStdin() if stdin is None else stdin
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode or 0


def test_worker_process_round_trips_envelopes(tmp_path: Path) -> None:
    worker = _write_worker(
        tmp_path,
        """
import json
import sys

for line in sys.stdin:
    msg = json.loads(line)
    sys.stdout.write(json.dumps({
        "schema_version": 1,
        "kind": "result",
        "type": "voice.transcribe",
        "request_id": msg["request_id"],
        "timestamp_ms": 1001,
        "deadline_ms": 0,
        "payload": {"path": msg["payload"]["path"], "ok": True},
    }) + "\\n")
    sys.stdout.flush()
""".strip(),
    )
    runtime = WorkerProcessRuntime(
        WorkerProcessConfig(
            name="echo",
            argv=[sys.executable, "-u", str(worker)],
            receive_queue_size=4,
        )
    )

    runtime.start()
    try:
        assert runtime.send_command(
            type="voice.transcribe",
            payload={"path": "/tmp/audio.wav"},
            request_id="req-1",
            timestamp_ms=1000,
            deadline_ms=5000,
        )
        messages = runtime.wait_for_messages(count=1, timeout_seconds=2.0)
    finally:
        runtime.stop(grace_seconds=0.2)

    assert len(messages) == 1
    assert messages[0].kind == "result"
    assert messages[0].type == "voice.transcribe"
    assert messages[0].request_id == "req-1"
    assert messages[0].payload == {"path": "/tmp/audio.wav", "ok": True}
    snapshot = runtime.snapshot()
    assert snapshot.received_messages == 1
    assert snapshot.protocol_errors == 0


def test_worker_process_counts_malformed_stdout(tmp_path: Path) -> None:
    worker = _write_worker(
        tmp_path,
        """
import sys
sys.stdout.write("not json\\n")
sys.stdout.flush()
""".strip(),
    )
    runtime = WorkerProcessRuntime(
        WorkerProcessConfig(name="bad", argv=[sys.executable, "-u", str(worker)])
    )

    runtime.start()
    try:
        assert runtime.wait_until_exited(timeout_seconds=2.0)
        runtime.stop(grace_seconds=0.1)
        snapshot = runtime.snapshot()
    finally:
        runtime.stop(grace_seconds=0.1)

    assert snapshot.protocol_errors >= 1
    assert snapshot.received_messages == 0


def test_worker_process_counts_invalid_utf8_stdout_without_losing_reader(tmp_path: Path) -> None:
    worker = _write_worker(
        tmp_path,
        """
import sys
sys.stdout.buffer.write(b"\\xff\\n")
sys.stdout.buffer.write(b'{"schema_version":1,"kind":"event","type":"voice.ready","request_id":null,"timestamp_ms":1,"deadline_ms":0,"payload":{"ok":true}}\\n')
sys.stdout.flush()
""".strip(),
    )
    runtime = WorkerProcessRuntime(
        WorkerProcessConfig(name="bad-utf8", argv=[sys.executable, "-u", str(worker)])
    )

    runtime.start()
    try:
        messages = runtime.wait_for_messages(count=1, timeout_seconds=2.0)
        runtime.stop(grace_seconds=0.1)
        snapshot = runtime.snapshot()
    finally:
        runtime.stop(grace_seconds=0.1)

    assert len(messages) == 1
    assert messages[0].type == "voice.ready"
    assert snapshot.protocol_errors >= 1
    assert snapshot.received_messages == 1


def test_worker_process_stop_is_bounded_for_stuck_worker(tmp_path: Path) -> None:
    worker = _write_worker(
        tmp_path,
        """
import time
time.sleep(60)
""".strip(),
    )
    runtime = WorkerProcessRuntime(
        WorkerProcessConfig(name="stuck", argv=[sys.executable, "-u", str(worker)])
    )

    runtime.start()
    runtime.stop(grace_seconds=0.05)

    snapshot = runtime.snapshot()
    assert snapshot.running is False
    assert snapshot.terminated is True


def test_worker_process_stop_is_bounded_when_send_lock_is_busy(tmp_path: Path) -> None:
    worker = _write_worker(
        tmp_path,
        """
import time
time.sleep(60)
""".strip(),
    )
    runtime = WorkerProcessRuntime(
        WorkerProcessConfig(name="contended", argv=[sys.executable, "-u", str(worker)])
    )

    runtime.start()
    # Intentionally reaches into the private lock to reproduce send/stop contention.
    runtime._stdin_lock.acquire()
    stop_thread = threading.Thread(
        target=runtime.stop,
        kwargs={"grace_seconds": 0.05},
        daemon=True,
    )

    try:
        stop_thread.start()
        stop_thread.join(timeout=0.5)
        assert stop_thread.is_alive() is False
    finally:
        if runtime._stdin_lock.locked():
            runtime._stdin_lock.release()
        stop_thread.join(timeout=2.0)
        runtime.stop(grace_seconds=0.05)

    snapshot = runtime.snapshot()
    assert snapshot.running is False
    assert snapshot.terminated is True


def test_worker_process_stop_is_bounded_when_graceful_send_blocks() -> None:
    runtime = WorkerProcessRuntime(WorkerProcessConfig(name="blocked", argv=["unused"]))
    process = _FakeProcess()
    runtime._process = cast(Any, process)
    stop_thread = threading.Thread(
        target=runtime.stop,
        kwargs={"grace_seconds": 0.05},
        daemon=True,
    )

    try:
        stop_thread.start()
        assert process.stdin.write_entered.wait(timeout=0.5)
        stop_thread.join(timeout=0.5)
        assert stop_thread.is_alive() is False
    finally:
        process.stdin.release_write.set()
        stop_thread.join(timeout=2.0)

    assert process.terminated is True


def test_worker_process_send_uses_bounded_outbound_queue_when_stdin_blocks() -> None:
    runtime = WorkerProcessRuntime(
        WorkerProcessConfig(
            name="blocked-send",
            argv=["unused"],
            send_queue_size=1,
        )
    )
    process = _FakeProcess()
    runtime._process = cast(Any, process)
    runtime._start_writer()

    try:
        assert runtime.send_command(type="voice.transcribe", payload={}, request_id="req-1")
        assert process.stdin.write_entered.wait(timeout=0.5)
        assert runtime.send_command(type="voice.transcribe", payload={}, request_id="req-2")

        started_at = time.monotonic()
        assert (
            runtime.send_command(type="voice.transcribe", payload={}, request_id="req-3")
            is False
        )
        elapsed_seconds = time.monotonic() - started_at
        snapshot = runtime.snapshot()
    finally:
        process.stdin.release_write.set()

    assert elapsed_seconds < 0.1
    assert snapshot.dropped_sends == 1
    assert snapshot.queued_sends == 1


def test_worker_process_writer_survives_json_encoding_failure() -> None:
    stdin = _RecordingStdin()
    process = _FakeProcess(stdin=stdin)
    runtime = WorkerProcessRuntime(WorkerProcessConfig(name="encoding", argv=["unused"]))
    runtime._process = cast(Any, process)
    runtime._start_writer()

    try:
        assert runtime.send_command(
            type="voice.transcribe",
            payload={"raw": b"not-json"},
            request_id="bad",
        )
        assert runtime.send_command(
            type="voice.transcribe",
            payload={"path": "/tmp/audio.wav"},
            request_id="good",
        )

        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            snapshot = runtime.snapshot()
            if snapshot.send_failures == 1 and snapshot.sent_messages == 1:
                break
            time.sleep(0.01)
        else:
            snapshot = runtime.snapshot()
    finally:
        runtime._request_writer_shutdown()
        runtime._join_writer(timeout_seconds=0.5)

    assert snapshot.send_failures == 1
    assert snapshot.sent_messages == 1
    assert len(stdin.writes) == 1
    assert b'"request_id":"good"' in stdin.writes[0]


def test_worker_process_writer_exits_after_process_exit() -> None:
    runtime = WorkerProcessRuntime(WorkerProcessConfig(name="exited", argv=["unused"]))
    process = _FakeProcess()
    process.returncode = 7
    runtime._process = cast(Any, process)

    runtime._start_writer()
    assert runtime._writer_thread is not None
    runtime._writer_thread.join(timeout=0.5)

    assert runtime._writer_thread.is_alive() is False
