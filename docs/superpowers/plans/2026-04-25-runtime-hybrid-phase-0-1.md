# Runtime Hybrid Phase 0-1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the responsiveness, memory, and worker-runtime foundation required before moving voice or network into sidecar processes.

**Architecture:** This plan implements the prerequisite slice from `docs/superpowers/specs/2026-04-25-runtime-hybrid-architecture-design.md`: Phase 0 instrumentation plus Phase 1 worker runtime. The Python supervisor remains the sole owner of UI, state, bus, scheduler, music/call coordination, and navigation. Worker support is added as an idle foundation with fake-worker tests; no production subsystem is moved out of process in this plan.

**Tech Stack:** Python 3.12, stdlib `subprocess`, `threading`, `queue`, NDJSON over stdio, existing `RuntimeLoopService`, `MainThreadScheduler`, `Bus`, `RuntimeStatusService`, `uv`, pytest. No ZeroMQ, msgpack, asyncio migration, Go worker, or network sidecar in this plan.

---

## Scope Check

The approved design covers multiple phases: instrumentation, worker runtime, Go voice worker, Python network worker, and a later VoIP decision gate. A single implementation plan for all phases would be too broad. This plan intentionally covers only the first executable slice:

1. Phase 0 responsiveness and memory baseline instrumentation.
2. Phase 1 neutral worker runtime with protocol, bounded queues, restart/backoff, cancellation, and fake-worker tests.

Follow-up plans should be written after this lands:

1. Go cloud voice worker.
2. Python network worker.
3. VoIP sidecar feasibility, only if measurements prove it is necessary.

---

## File Structure

Create:

- `yoyopod/core/diagnostics/memory.py`
  - Parses Linux `/proc/<pid>/smaps_rollup` and `/proc/<pid>/status`.
  - Returns PSS/RSS/private-dirty snapshots without adding runtime dependencies.

- `yoyopod/core/workers/__init__.py`
  - Public exports for worker protocol and supervisor primitives.

- `yoyopod/core/workers/protocol.py`
  - Validates and serializes worker NDJSON envelopes.
  - Contains no process-management logic.

- `yoyopod/core/workers/process.py`
  - Owns one child process, stdout/stderr reader threads, bounded receive queue, send lock, stop/terminate/kill behavior, and process stats.

- `yoyopod/core/workers/supervisor.py`
  - Owns named workers, restart/backoff state, non-blocking polling, request timeout/cancellation bookkeeping, and status snapshots.

- `tests/core/diagnostics/test_memory.py`
  - Unit tests for PSS/RSS parsing and unavailable `/proc` behavior.

- `tests/core/workers/test_protocol.py`
  - Unit tests for envelope validation.

- `tests/core/workers/test_process.py`
  - Integration tests with temporary fake worker scripts.

- `tests/core/workers/test_supervisor.py`
  - Unit/integration tests for restart/backoff, timeout, degraded state, and status snapshots.

Modify:

- `yoyopod/core/status.py`
  - Extend `RuntimeMetricsStore` with latency samples and expose status snapshot keys.
  - Include current-process memory snapshot in runtime status.

- `yoyopod/core/application.py`
  - Add `worker_supervisor`.
  - Add `note_visible_refresh()`.
  - Stop workers before legacy runtime resources during shutdown.

- `yoyopod/core/loop.py`
  - Record main-thread drain duration.
  - Record visible refresh after screen refresh.
  - Poll the worker supervisor once per loop iteration without blocking.
  - Surface worker queue/restart/request metrics in `timing_snapshot()`.

- `yoyopod/core/events.py`
  - Add worker-domain event dataclasses that can be published on the main-thread bus.

- `yoyopod/core/__init__.py`
  - Export new worker event dataclasses through the existing lazy `_PUBLIC_EXPORTS` map.

- `docs/PI_PROFILING_WORKFLOW.md`
  - Add the exact target-hardware commands for baseline PSS and responsiveness collection.

---

## Task 1: Runtime Responsiveness Metrics

**Files:**

- Modify: `yoyopod/core/status.py`
- Modify: `yoyopod/core/application.py`
- Test: `tests/core/test_runtime_metrics.py`

- [ ] **Step 1: Write failing tests for latency samples**

Add these tests to `tests/core/test_runtime_metrics.py`:

```python
def test_runtime_metrics_records_input_to_action_latency() -> None:
    store = RuntimeMetricsStore()

    store.note_input_activity(SimpleNamespace(value="select"), captured_at=10.0)
    store.note_handled_input(action_name="select", handled_at=10.035)

    snapshot = store.responsiveness_snapshot(now=11.0)

    assert snapshot["responsiveness_input_to_action_count"] == 1
    assert snapshot["responsiveness_input_to_action_p95_ms"] == 35.0
    assert snapshot["responsiveness_input_to_action_last_ms"] == 35.0
    assert snapshot["responsiveness_last_input_to_action_name"] == "select"


def test_runtime_metrics_records_action_to_visible_refresh_latency() -> None:
    store = RuntimeMetricsStore()

    store.note_input_activity(SimpleNamespace(value="down"), captured_at=20.0)
    store.note_handled_input(action_name="down", handled_at=20.010)
    store.note_visible_refresh(refreshed_at=20.085)

    snapshot = store.responsiveness_snapshot(now=21.0)

    assert snapshot["responsiveness_action_to_visible_count"] == 1
    assert snapshot["responsiveness_action_to_visible_p95_ms"] == 75.0
    assert snapshot["responsiveness_action_to_visible_last_ms"] == 75.0
    assert snapshot["responsiveness_last_visible_action_name"] == "down"


def test_runtime_metrics_ignores_refresh_without_handled_input() -> None:
    store = RuntimeMetricsStore()

    store.note_visible_refresh(refreshed_at=30.0)

    snapshot = store.responsiveness_snapshot(now=31.0)

    assert snapshot["responsiveness_action_to_visible_count"] == 0
    assert snapshot["responsiveness_action_to_visible_p95_ms"] is None
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/core/test_runtime_metrics.py -q
```

Expected: failures mentioning `RuntimeMetricsStore` has no `responsiveness_snapshot` or `note_visible_refresh`.

- [ ] **Step 3: Add metrics dataclass and deques**

In `yoyopod/core/status.py`, add imports:

```python
from collections import deque
from dataclasses import dataclass
from typing import Literal
```

Add below the `TYPE_CHECKING` block:

```python
LatencyKind = Literal["input_to_action", "action_to_visible"]


@dataclass(frozen=True, slots=True)
class RuntimeLatencySample:
    """One user-visible responsiveness measurement."""

    kind: LatencyKind
    action_name: str | None
    duration_seconds: float
    recorded_at: float
```

In `RuntimeMetricsStore.__init__()`, add:

```python
self._input_to_action_samples: deque[RuntimeLatencySample] = deque(maxlen=256)
self._action_to_visible_samples: deque[RuntimeLatencySample] = deque(maxlen=256)
self._last_handled_input_for_refresh_at = 0.0
self._last_handled_input_for_refresh_action_name: str | None = None
```

- [ ] **Step 4: Implement latency recording methods**

Update `RuntimeMetricsStore.note_handled_input()`:

```python
def note_handled_input(
    self,
    *,
    action_name: str | None,
    handled_at: float,
) -> None:
    """Record semantic user activity after the coordinator handles it."""

    self.last_input_handled_at = handled_at
    self.last_input_handled_action_name = action_name
    self._last_handled_input_for_refresh_at = handled_at
    self._last_handled_input_for_refresh_action_name = action_name
    if self.last_input_activity_at <= 0.0:
        return

    duration_seconds = max(0.0, handled_at - self.last_input_activity_at)
    self._input_to_action_samples.append(
        RuntimeLatencySample(
            kind="input_to_action",
            action_name=action_name,
            duration_seconds=duration_seconds,
            recorded_at=handled_at,
        )
    )
```

Add:

```python
def note_visible_refresh(self, *, refreshed_at: float) -> None:
    """Record the first visible refresh after the latest handled input."""

    if self._last_handled_input_for_refresh_at <= 0.0:
        return

    duration_seconds = max(0.0, refreshed_at - self._last_handled_input_for_refresh_at)
    self._action_to_visible_samples.append(
        RuntimeLatencySample(
            kind="action_to_visible",
            action_name=self._last_handled_input_for_refresh_action_name,
            duration_seconds=duration_seconds,
            recorded_at=refreshed_at,
        )
    )
    self._last_handled_input_for_refresh_at = 0.0
    self._last_handled_input_for_refresh_action_name = None

def responsiveness_snapshot(self, *, now: float) -> dict[str, float | int | str | None]:
    """Return compact responsiveness metrics for status and diagnostics."""

    input_samples = list(self._input_to_action_samples)
    visible_samples = list(self._action_to_visible_samples)
    last_input = input_samples[-1] if input_samples else None
    last_visible = visible_samples[-1] if visible_samples else None
    return {
        "responsiveness_input_to_action_count": len(input_samples),
        "responsiveness_input_to_action_p50_ms": _percentile_ms(input_samples, 0.50),
        "responsiveness_input_to_action_p95_ms": _percentile_ms(input_samples, 0.95),
        "responsiveness_input_to_action_max_ms": _max_ms(input_samples),
        "responsiveness_input_to_action_last_ms": _sample_ms(last_input),
        "responsiveness_last_input_to_action_name": (
            last_input.action_name if last_input is not None else None
        ),
        "responsiveness_action_to_visible_count": len(visible_samples),
        "responsiveness_action_to_visible_p50_ms": _percentile_ms(visible_samples, 0.50),
        "responsiveness_action_to_visible_p95_ms": _percentile_ms(visible_samples, 0.95),
        "responsiveness_action_to_visible_max_ms": _max_ms(visible_samples),
        "responsiveness_action_to_visible_last_ms": _sample_ms(last_visible),
        "responsiveness_last_visible_action_name": (
            last_visible.action_name if last_visible is not None else None
        ),
        "responsiveness_snapshot_age_seconds": 0.0 if now > 0.0 else None,
    }
```

Add helper functions near `_jsonify()`:

```python
def _sample_ms(sample: RuntimeLatencySample | None) -> float | None:
    if sample is None:
        return None
    return round(sample.duration_seconds * 1000.0, 3)


def _max_ms(samples: list[RuntimeLatencySample]) -> float | None:
    if not samples:
        return None
    return round(max(sample.duration_seconds for sample in samples) * 1000.0, 3)


def _percentile_ms(samples: list[RuntimeLatencySample], ratio: float) -> float | None:
    if not samples:
        return None
    ordered = sorted(sample.duration_seconds for sample in samples)
    index = int(round((len(ordered) - 1) * ratio))
    return round(ordered[index] * 1000.0, 3)
```

- [ ] **Step 5: Add app methods**

In `yoyopod/core/application.py`, replace `note_input_activity()` with:

```python
def note_input_activity(
    self,
    action: object,
    _data: Any | None = None,
    *,
    captured_at: float | None = None,
) -> None:
    """Record raw or semantic input activity before the coordinator drains it."""

    self.runtime_metrics.note_input_activity(action, _data, captured_at=captured_at)
```

Then add after `note_handled_input()`:

```python
def note_visible_refresh(self, *, refreshed_at: float) -> None:
    """Record that a visible screen refresh happened on the coordinator thread."""

    self.runtime_metrics.note_visible_refresh(refreshed_at=refreshed_at)
```

- [ ] **Step 6: Run tests**

Run:

```bash
uv run pytest tests/core/test_runtime_metrics.py -q
```

Expected: all tests in the file pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add yoyopod/core/status.py yoyopod/core/application.py tests/core/test_runtime_metrics.py
git commit -m "feat: track runtime responsiveness latency"
```

---

## Task 2: Hook Refresh and Drain Metrics Into the Runtime Loop

**Files:**

- Modify: `yoyopod/core/loop.py`
- Modify: `yoyopod/core/status.py`
- Test: create `tests/core/test_runtime_loop_metrics.py`

- [ ] **Step 1: Write focused loop tests**

Create `tests/core/test_runtime_loop_metrics.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

from yoyopod.core.application import YoyoPodApp


class _ScreenManager:
    def __init__(self) -> None:
        self.refresh_count = 0

    def get_current_screen(self) -> object:
        return SimpleNamespace(route_name="hub")

    def refresh_current_screen_for_visible_tick(self) -> None:
        self.refresh_count += 1


def test_visible_screen_refresh_records_action_to_visible_latency() -> None:
    app = YoyoPodApp()
    screen_manager = _ScreenManager()
    app.screen_manager = screen_manager
    app.app_state_runtime = SimpleNamespace(get_state_name=lambda: "idle")
    app.call_interruption_policy = SimpleNamespace(music_interrupted_by_call=False)
    app._screen_awake = True
    app.note_input_activity(SimpleNamespace(value="select"), 0, captured_at=100.0)
    app.note_handled_input(action_name="select", handled_at=100.020)

    app.runtime_loop.run_iteration(
        monotonic_now=100.100,
        current_time=200.0,
        last_screen_update=198.0,
        screen_update_interval=1.0,
    )

    snapshot = app.runtime_metrics.responsiveness_snapshot(now=101.0)
    assert screen_manager.refresh_count == 1
    assert snapshot["responsiveness_action_to_visible_count"] == 1
    assert snapshot["responsiveness_last_visible_action_name"] == "select"


def test_timing_snapshot_includes_drain_duration() -> None:
    app = YoyoPodApp()
    app.runtime_loop.process_pending_main_thread_actions()

    snapshot = app.runtime_loop.timing_snapshot(now=1.0)

    assert "runtime_main_thread_drain_seconds" in snapshot
    assert snapshot["runtime_main_thread_drain_seconds"] is not None
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/core/test_runtime_loop_metrics.py -q
```

Expected: failure because visible refresh does not record latency and drain duration is not exposed.

- [ ] **Step 3: Store main-thread drain duration**

In `yoyopod/core/loop.py`, add an instance field in `RuntimeLoopService.__init__()`:

```python
self._last_main_thread_drain_duration_seconds = 0.0
```

At the end of `process_pending_main_thread_actions()` before `return`, add:

```python
self._last_main_thread_drain_duration_seconds = max(0.0, time.monotonic() - started_at)
```

At the end of `_process_pending_main_thread_actions_for_iteration()` before `return`, add:

```python
self._last_main_thread_drain_duration_seconds = max(0.0, time.monotonic() - started_at)
```

- [ ] **Step 4: Record visible refresh**

In `RuntimeLoopService.run_iteration()`, replace the visible refresh block:

```python
self._measure_blocking_span(
    "visible_screen_refresh",
    screen_manager.refresh_current_screen_for_visible_tick,
)
return current_time
```

with:

```python
self._measure_blocking_span(
    "visible_screen_refresh",
    screen_manager.refresh_current_screen_for_visible_tick,
)
self.app.note_visible_refresh(refreshed_at=time.monotonic())
return current_time
```

- [ ] **Step 5: Expose drain duration in timing snapshot**

In `RuntimeLoopService.timing_snapshot()`, add:

```python
"runtime_main_thread_drain_seconds": (
    self._last_main_thread_drain_duration_seconds
    if self._last_loop_iteration_started_at > 0.0
    or self._last_main_thread_drain_duration_seconds > 0.0
    else None
),
```

- [ ] **Step 6: Expose responsiveness snapshot through runtime status**

In `RuntimeStatusService.get_status()`, add this near the final `**self.app.runtime_loop.timing_snapshot(...)` merge:

```python
**runtime_metrics.responsiveness_snapshot(now=monotonic_now),
```

The end of the returned dict should include both responsiveness keys and loop timing keys.

- [ ] **Step 7: Run tests**

Run:

```bash
uv run pytest tests/core/test_runtime_metrics.py tests/core/test_runtime_loop_metrics.py -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

Run:

```bash
git add yoyopod/core/loop.py yoyopod/core/status.py yoyopod/core/application.py tests/core/test_runtime_loop_metrics.py tests/core/test_runtime_metrics.py
git commit -m "feat: expose runtime responsiveness diagnostics"
```

---

## Task 3: PSS/RSS Memory Snapshot Helper

**Files:**

- Create: `yoyopod/core/diagnostics/memory.py`
- Modify: `yoyopod/core/status.py`
- Test: `tests/core/diagnostics/test_memory.py`

- [ ] **Step 1: Write memory parser tests**

Create `tests/core/diagnostics/test_memory.py`:

```python
from __future__ import annotations

from pathlib import Path

from yoyopod.core.diagnostics.memory import (
    ProcessMemorySnapshot,
    collect_process_memory,
    parse_smaps_rollup,
    parse_status_rss_kb,
)


def test_parse_smaps_rollup_extracts_pss_rss_and_private_dirty() -> None:
    text = """
Rss:               42184 kB
Pss:               19928 kB
Private_Dirty:      7120 kB
SwapPss:              0 kB
""".strip()

    snapshot = parse_smaps_rollup(text, pid=123)

    assert snapshot == ProcessMemorySnapshot(
        pid=123,
        rss_kb=42184,
        pss_kb=19928,
        private_dirty_kb=7120,
        source="smaps_rollup",
    )


def test_parse_status_rss_kb_extracts_vmrss() -> None:
    text = """
Name:\tpython
VmRSS:\t   35100 kB
Threads:\t4
""".strip()

    assert parse_status_rss_kb(text) == 35100


def test_collect_process_memory_uses_status_when_smaps_missing(tmp_path: Path) -> None:
    proc_dir = tmp_path / "123"
    proc_dir.mkdir(parents=True)
    (proc_dir / "status").write_text("VmRSS:\t2048 kB\n", encoding="utf-8")

    snapshot = collect_process_memory(pid=123, proc_root=tmp_path)

    assert snapshot.pid == 123
    assert snapshot.rss_kb == 2048
    assert snapshot.pss_kb is None
    assert snapshot.source == "status"


def test_collect_process_memory_returns_unavailable_when_proc_missing(tmp_path: Path) -> None:
    snapshot = collect_process_memory(pid=999, proc_root=tmp_path)

    assert snapshot.pid == 999
    assert snapshot.rss_kb is None
    assert snapshot.pss_kb is None
    assert snapshot.source == "unavailable"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/core/diagnostics/test_memory.py -q
```

Expected: import failure because `yoyopod.core.diagnostics.memory` does not exist.

- [ ] **Step 3: Implement memory helper**

Create `yoyopod/core/diagnostics/memory.py`:

```python
"""Small process memory snapshot helpers for Pi diagnostics."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProcessMemorySnapshot:
    """Best-effort memory snapshot for one process."""

    pid: int
    rss_kb: int | None
    pss_kb: int | None
    private_dirty_kb: int | None
    source: str


def collect_process_memory(
    *,
    pid: int | None = None,
    proc_root: Path = Path("/proc"),
) -> ProcessMemorySnapshot:
    """Return PSS/RSS when Linux procfs exposes it, else a safe unavailable snapshot."""

    actual_pid = os.getpid() if pid is None else int(pid)
    proc_dir = proc_root / str(actual_pid)
    smaps_path = proc_dir / "smaps_rollup"
    status_path = proc_dir / "status"

    if smaps_path.exists():
        return parse_smaps_rollup(smaps_path.read_text(encoding="utf-8"), pid=actual_pid)

    if status_path.exists():
        return ProcessMemorySnapshot(
            pid=actual_pid,
            rss_kb=parse_status_rss_kb(status_path.read_text(encoding="utf-8")),
            pss_kb=None,
            private_dirty_kb=None,
            source="status",
        )

    return ProcessMemorySnapshot(
        pid=actual_pid,
        rss_kb=None,
        pss_kb=None,
        private_dirty_kb=None,
        source="unavailable",
    )


def parse_smaps_rollup(text: str, *, pid: int) -> ProcessMemorySnapshot:
    """Parse the memory fields used by the runtime architecture spec."""

    values = _parse_kb_fields(text)
    return ProcessMemorySnapshot(
        pid=pid,
        rss_kb=values.get("Rss"),
        pss_kb=values.get("Pss"),
        private_dirty_kb=values.get("Private_Dirty"),
        source="smaps_rollup",
    )


def parse_status_rss_kb(text: str) -> int | None:
    """Parse VmRSS from /proc/<pid>/status."""

    return _parse_kb_fields(text).get("VmRSS")


def _parse_kb_fields(text: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for raw_line in text.splitlines():
        if ":" not in raw_line:
            continue
        key, raw_value = raw_line.split(":", 1)
        parts = raw_value.strip().split()
        if len(parts) < 2 or parts[1] != "kB":
            continue
        try:
            values[key.strip()] = int(parts[0])
        except ValueError:
            continue
    return values
```

- [ ] **Step 4: Add memory fields to status**

In `yoyopod/core/status.py`, add:

```python
from yoyopod.core.diagnostics.memory import collect_process_memory
```

Inside `RuntimeStatusService.get_status()`, after `monotonic_now = time.monotonic()`, add:

```python
process_memory = collect_process_memory()
```

Add these keys to the returned dict:

```python
"process_memory_pid": process_memory.pid,
"process_memory_rss_kb": process_memory.rss_kb,
"process_memory_pss_kb": process_memory.pss_kb,
"process_memory_private_dirty_kb": process_memory.private_dirty_kb,
"process_memory_source": process_memory.source,
```

- [ ] **Step 5: Run tests**

Run:

```bash
uv run pytest tests/core/diagnostics/test_memory.py tests/core/test_runtime_metrics.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add yoyopod/core/diagnostics/memory.py yoyopod/core/status.py tests/core/diagnostics/test_memory.py
git commit -m "feat: add process memory diagnostics"
```

---

## Task 4: Worker NDJSON Protocol

**Files:**

- Create: `yoyopod/core/workers/__init__.py`
- Create: `yoyopod/core/workers/protocol.py`
- Test: `tests/core/workers/test_protocol.py`

- [ ] **Step 1: Write protocol tests**

Create `tests/core/workers/test_protocol.py`:

```python
from __future__ import annotations

import json

import pytest

from yoyopod.core.workers.protocol import (
    WorkerEnvelope,
    WorkerProtocolError,
    encode_envelope,
    make_envelope,
    parse_envelope_line,
)


def test_parse_envelope_line_accepts_valid_ndjson() -> None:
    line = json.dumps(
        {
            "schema_version": 1,
            "kind": "event",
            "type": "network.status",
            "request_id": "req-1",
            "timestamp_ms": 1777100000000,
            "deadline_ms": 5000,
            "payload": {"online": True},
        }
    )

    envelope = parse_envelope_line(line)

    assert envelope == WorkerEnvelope(
        schema_version=1,
        kind="event",
        type="network.status",
        request_id="req-1",
        timestamp_ms=1777100000000,
        deadline_ms=5000,
        payload={"online": True},
    )


def test_parse_envelope_line_rejects_unknown_schema() -> None:
    with pytest.raises(WorkerProtocolError, match="schema_version"):
        parse_envelope_line('{"schema_version": 2, "kind": "event", "type": "x", "payload": {}}')


def test_parse_envelope_line_rejects_non_dict_payload() -> None:
    with pytest.raises(WorkerProtocolError, match="payload"):
        parse_envelope_line('{"schema_version": 1, "kind": "event", "type": "x", "payload": []}')


def test_encode_envelope_returns_newline_terminated_json() -> None:
    envelope = make_envelope(
        kind="command",
        type="voice.cancel",
        payload={"request_id": "abc"},
        request_id="abc",
        timestamp_ms=1777100000001,
        deadline_ms=100,
    )

    encoded = encode_envelope(envelope)

    assert encoded.endswith("\n")
    assert parse_envelope_line(encoded) == envelope
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/core/workers/test_protocol.py -q
```

Expected: import failure because worker protocol package does not exist.

- [ ] **Step 3: Implement protocol module**

Create `yoyopod/core/workers/protocol.py`:

```python
"""Language-neutral NDJSON protocol for YoYoPod worker sidecars."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SUPPORTED_SCHEMA_VERSION = 1
VALID_KINDS = frozenset({"command", "event", "result", "error", "heartbeat"})


class WorkerProtocolError(ValueError):
    """Raised when one worker protocol line cannot be accepted."""


@dataclass(frozen=True, slots=True)
class WorkerEnvelope:
    """One validated worker protocol message."""

    schema_version: int
    kind: str
    type: str
    request_id: str | None = None
    timestamp_ms: int = 0
    deadline_ms: int = 0
    payload: dict[str, Any] = field(default_factory=dict)


def make_envelope(
    *,
    kind: str,
    type: str,
    payload: dict[str, Any] | None = None,
    request_id: str | None = None,
    timestamp_ms: int = 0,
    deadline_ms: int = 0,
) -> WorkerEnvelope:
    """Create a validated envelope using the current schema."""

    return _validate(
        {
            "schema_version": SUPPORTED_SCHEMA_VERSION,
            "kind": kind,
            "type": type,
            "request_id": request_id,
            "timestamp_ms": timestamp_ms,
            "deadline_ms": deadline_ms,
            "payload": dict(payload or {}),
        }
    )


def parse_envelope_line(line: str | bytes) -> WorkerEnvelope:
    """Parse one newline-delimited JSON worker message."""

    if isinstance(line, bytes):
        line = line.decode("utf-8", errors="replace")
    try:
        raw = json.loads(line)
    except json.JSONDecodeError as exc:
        raise WorkerProtocolError(f"invalid JSON: {exc.msg}") from exc
    return _validate(raw)


def encode_envelope(envelope: WorkerEnvelope) -> str:
    """Serialize one envelope as stable newline-delimited JSON."""

    payload = {
        "schema_version": envelope.schema_version,
        "kind": envelope.kind,
        "type": envelope.type,
        "request_id": envelope.request_id,
        "timestamp_ms": envelope.timestamp_ms,
        "deadline_ms": envelope.deadline_ms,
        "payload": envelope.payload,
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n"


def _validate(raw: object) -> WorkerEnvelope:
    if not isinstance(raw, dict):
        raise WorkerProtocolError("worker envelope must be a JSON object")

    schema_version = raw.get("schema_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise WorkerProtocolError(
            f"unsupported schema_version {schema_version!r}; expected {SUPPORTED_SCHEMA_VERSION}"
        )

    kind = raw.get("kind")
    if not isinstance(kind, str) or kind not in VALID_KINDS:
        raise WorkerProtocolError(f"invalid kind {kind!r}")

    message_type = raw.get("type")
    if not isinstance(message_type, str) or not message_type:
        raise WorkerProtocolError("type must be a non-empty string")

    payload = raw.get("payload", {})
    if not isinstance(payload, dict):
        raise WorkerProtocolError("payload must be an object")

    request_id = raw.get("request_id")
    if request_id is not None and not isinstance(request_id, str):
        raise WorkerProtocolError("request_id must be a string or null")

    return WorkerEnvelope(
        schema_version=SUPPORTED_SCHEMA_VERSION,
        kind=kind,
        type=message_type,
        request_id=request_id,
        timestamp_ms=_coerce_non_negative_int(raw.get("timestamp_ms", 0), "timestamp_ms"),
        deadline_ms=_coerce_non_negative_int(raw.get("deadline_ms", 0), "deadline_ms"),
        payload=dict(payload),
    )


def _coerce_non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise WorkerProtocolError(f"{field_name} must be a non-negative integer")
    try:
        coerced = int(value)
    except (TypeError, ValueError) as exc:
        raise WorkerProtocolError(f"{field_name} must be a non-negative integer") from exc
    if coerced < 0:
        raise WorkerProtocolError(f"{field_name} must be a non-negative integer")
    return coerced
```

Create `yoyopod/core/workers/__init__.py`:

```python
"""Worker process primitives for YoYoPod runtime sidecars."""

from yoyopod.core.workers.protocol import (
    SUPPORTED_SCHEMA_VERSION,
    WorkerEnvelope,
    WorkerProtocolError,
    encode_envelope,
    make_envelope,
    parse_envelope_line,
)

__all__ = [
    "SUPPORTED_SCHEMA_VERSION",
    "WorkerEnvelope",
    "WorkerProtocolError",
    "encode_envelope",
    "make_envelope",
    "parse_envelope_line",
]
```

- [ ] **Step 4: Run tests**

Run:

```bash
uv run pytest tests/core/workers/test_protocol.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add yoyopod/core/workers/__init__.py yoyopod/core/workers/protocol.py tests/core/workers/test_protocol.py
git commit -m "feat: add worker message protocol"
```

---

## Task 5: Single Worker Process Runtime

**Files:**

- Create: `yoyopod/core/workers/process.py`
- Modify: `yoyopod/core/workers/__init__.py`
- Test: `tests/core/workers/test_process.py`

- [ ] **Step 1: Write process runtime tests**

Create `tests/core/workers/test_process.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

from yoyopod.core.workers.process import WorkerProcessConfig, WorkerProcessRuntime


def _write_worker(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "fake_worker.py"
    path.write_text(body, encoding="utf-8")
    return path


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
        "type": msg["type"],
        "request_id": msg.get("request_id"),
        "timestamp_ms": msg.get("timestamp_ms", 0),
        "deadline_ms": 0,
        "payload": {"ok": True, "echo": msg.get("payload", {})},
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
    assert messages[0].request_id == "req-1"
    assert messages[0].payload["echo"] == {"path": "/tmp/audio.wav"}


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
        runtime.wait_until_exited(timeout_seconds=2.0)
        runtime.drain_messages()
        snapshot = runtime.snapshot()
    finally:
        runtime.stop(grace_seconds=0.1)

    assert snapshot.protocol_errors >= 1


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
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/core/workers/test_process.py -q
```

Expected: import failure because `WorkerProcessRuntime` does not exist.

- [ ] **Step 3: Implement process runtime dataclasses**

Create `yoyopod/core/workers/process.py` with these imports and dataclasses:

```python
"""One child-process runtime for NDJSON worker sidecars."""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass, field
from queue import Empty, Full, Queue
from typing import TextIO

from loguru import logger

from yoyopod.core.workers.protocol import (
    WorkerEnvelope,
    WorkerProtocolError,
    encode_envelope,
    make_envelope,
    parse_envelope_line,
)


@dataclass(frozen=True, slots=True)
class WorkerProcessConfig:
    """Configuration for one managed worker process."""

    name: str
    argv: list[str]
    cwd: str | None = None
    env: dict[str, str] | None = None
    receive_queue_size: int = 64


@dataclass(frozen=True, slots=True)
class WorkerProcessSnapshot:
    """Observable state for one worker process."""

    name: str
    running: bool
    pid: int | None
    returncode: int | None
    received_messages: int
    protocol_errors: int
    dropped_messages: int
    stderr_lines: int
    terminated: bool
    killed: bool
```

- [ ] **Step 4: Implement process runtime core**

Continue `process.py`:

```python
class WorkerProcessRuntime:
    """Manage stdio for one worker child process without blocking the UI loop."""

    def __init__(self, config: WorkerProcessConfig) -> None:
        self.config = config
        self._process: subprocess.Popen[str] | None = None
        self._messages: Queue[WorkerEnvelope] = Queue(maxsize=max(1, config.receive_queue_size))
        self._stdin_lock = threading.Lock()
        self._reader_threads: list[threading.Thread] = []
        self._received_messages = 0
        self._protocol_errors = 0
        self._dropped_messages = 0
        self._stderr_lines = 0
        self._terminated = False
        self._killed = False

    def start(self) -> None:
        """Start the child process and stdout/stderr reader threads."""

        if self.running:
            return
        self._process = subprocess.Popen(
            self.config.argv,
            cwd=self.config.cwd,
            env=self.config.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert self._process.stdout is not None
        assert self._process.stderr is not None
        self._reader_threads = [
            self._start_reader("stdout", self._process.stdout),
            self._start_reader("stderr", self._process.stderr),
        ]

    @property
    def running(self) -> bool:
        """Return whether the child process is still alive."""

        return self._process is not None and self._process.poll() is None

    def send_command(
        self,
        *,
        type: str,
        payload: dict[str, object] | None = None,
        request_id: str | None = None,
        timestamp_ms: int = 0,
        deadline_ms: int = 0,
    ) -> bool:
        """Write one command envelope to worker stdin."""

        envelope = make_envelope(
            kind="command",
            type=type,
            payload=payload,
            request_id=request_id,
            timestamp_ms=timestamp_ms,
            deadline_ms=deadline_ms,
        )
        return self.send(envelope)

    def send(self, envelope: WorkerEnvelope) -> bool:
        """Write one envelope to worker stdin and report whether it was accepted."""

        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            return False
        with self._stdin_lock:
            try:
                process.stdin.write(encode_envelope(envelope))
                process.stdin.flush()
                return True
            except (BrokenPipeError, OSError, ValueError):
                return False
```

- [ ] **Step 5: Implement nonblocking drains and bounded stop**

Append:

```python
    def drain_messages(self, limit: int | None = None) -> list[WorkerEnvelope]:
        """Return available worker messages without blocking."""

        messages: list[WorkerEnvelope] = []
        while limit is None or len(messages) < limit:
            try:
                messages.append(self._messages.get_nowait())
            except Empty:
                break
        return messages

    def wait_for_messages(
        self,
        *,
        count: int,
        timeout_seconds: float,
    ) -> list[WorkerEnvelope]:
        """Testing helper that waits for a small number of messages."""

        deadline = time.monotonic() + timeout_seconds
        messages: list[WorkerEnvelope] = []
        while len(messages) < count and time.monotonic() < deadline:
            messages.extend(self.drain_messages(limit=count - len(messages)))
            if len(messages) >= count:
                break
            time.sleep(0.01)
        return messages

    def wait_until_exited(self, *, timeout_seconds: float) -> bool:
        """Testing helper that waits for process exit."""

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self._process is None or self._process.poll() is not None:
                return True
            time.sleep(0.01)
        return False

    def stop(self, *, grace_seconds: float = 1.0) -> None:
        """Stop the worker with bounded terminate/kill behavior."""

        process = self._process
        if process is None:
            return
        if process.poll() is None:
            try:
                self.send_command(type="worker.stop", payload={}, deadline_ms=int(grace_seconds * 1000))
            except Exception:
                pass
            deadline = time.monotonic() + max(0.0, grace_seconds)
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
        if process.poll() is None:
            process.terminate()
            self._terminated = True
            try:
                process.wait(timeout=max(0.05, grace_seconds))
            except subprocess.TimeoutExpired:
                process.kill()
                self._killed = True
                process.wait(timeout=1.0)
        self._join_readers(timeout_seconds=0.2)
```

- [ ] **Step 6: Implement readers and snapshot**

Append:

```python
    def snapshot(self) -> WorkerProcessSnapshot:
        """Return the observable process state."""

        process = self._process
        return WorkerProcessSnapshot(
            name=self.config.name,
            running=self.running,
            pid=process.pid if process is not None else None,
            returncode=process.poll() if process is not None else None,
            received_messages=self._received_messages,
            protocol_errors=self._protocol_errors,
            dropped_messages=self._dropped_messages,
            stderr_lines=self._stderr_lines,
            terminated=self._terminated,
            killed=self._killed,
        )

    def _start_reader(self, stream_name: str, stream: TextIO) -> threading.Thread:
        thread = threading.Thread(
            target=self._read_stream,
            args=(stream_name, stream),
            name=f"yoyopod-worker-{self.config.name}-{stream_name}",
            daemon=True,
        )
        thread.start()
        return thread

    def _read_stream(self, stream_name: str, stream: TextIO) -> None:
        for line in stream:
            if stream_name == "stderr":
                self._stderr_lines += 1
                logger.info("worker {} stderr: {}", self.config.name, line.rstrip())
                continue
            try:
                envelope = parse_envelope_line(line)
            except WorkerProtocolError:
                self._protocol_errors += 1
                continue
            try:
                self._messages.put_nowait(envelope)
                self._received_messages += 1
            except Full:
                self._dropped_messages += 1

    def _join_readers(self, *, timeout_seconds: float) -> None:
        for thread in self._reader_threads:
            thread.join(timeout=timeout_seconds)
```

- [ ] **Step 7: Export process runtime**

Update `yoyopod/core/workers/__init__.py`:

```python
from yoyopod.core.workers.process import (
    WorkerProcessConfig,
    WorkerProcessRuntime,
    WorkerProcessSnapshot,
)
```

Add these names to `__all__`.

- [ ] **Step 8: Run process tests**

Run:

```bash
uv run pytest tests/core/workers/test_protocol.py tests/core/workers/test_process.py -q
```

Expected: all tests pass.

- [ ] **Step 9: Commit**

Run:

```bash
git add yoyopod/core/workers/process.py yoyopod/core/workers/__init__.py tests/core/workers/test_process.py
git commit -m "feat: add worker process runtime"
```

---

## Task 6: Worker Supervisor, Events, and Status

**Files:**

- Create: `yoyopod/core/workers/supervisor.py`
- Modify: `yoyopod/core/events.py`
- Modify: `yoyopod/core/__init__.py`
- Modify: `yoyopod/core/workers/__init__.py`
- Test: `tests/core/workers/test_supervisor.py`

- [ ] **Step 1: Write supervisor tests**

Create `tests/core/workers/test_supervisor.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

from yoyopod.core.bus import Bus
from yoyopod.core.events import WorkerDomainStateChangedEvent
from yoyopod.core.scheduler import MainThreadScheduler
from yoyopod.core.workers.process import WorkerProcessConfig
from yoyopod.core.workers.supervisor import WorkerSupervisor


def _write_worker(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "fake_worker.py"
    path.write_text(body, encoding="utf-8")
    return path


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
    seen = []
    bus.subscribe(WorkerDomainStateChangedEvent, seen.append)
    supervisor = WorkerSupervisor(scheduler=scheduler, bus=bus)
    supervisor.register(
        "voice",
        WorkerProcessConfig(name="voice", argv=[sys.executable, "-u", str(worker)]),
    )

    supervisor.start("voice")
    try:
        supervisor.poll()
        bus.drain()
    finally:
        supervisor.stop_all(grace_seconds=0.1)

    snapshot = supervisor.snapshot()
    assert snapshot["voice"]["received_messages"] >= 1


def test_supervisor_marks_crashed_worker_degraded(tmp_path: Path) -> None:
    worker = _write_worker(tmp_path, "raise SystemExit(7)")
    bus = Bus()
    scheduler = MainThreadScheduler()
    events = []
    bus.subscribe(WorkerDomainStateChangedEvent, events.append)
    supervisor = WorkerSupervisor(scheduler=scheduler, bus=bus, restart_backoff_seconds=60.0)
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
        supervisor.poll(monotonic_now=100.0)
        supervisor.poll(monotonic_now=101.0)
        messages = supervisor.drain_worker_messages("voice")
    finally:
        supervisor.stop_all(grace_seconds=0.1)

    assert supervisor.snapshot()["voice"]["request_timeouts"] == 1
    assert any(message.type == "voice.cancelled" for message in messages)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/core/workers/test_supervisor.py -q
```

Expected: imports fail because supervisor and worker events do not exist.

- [ ] **Step 3: Add worker events**

In `yoyopod/core/events.py`, add:

```python
@dataclass(frozen=True, slots=True)
class WorkerDomainStateChangedEvent:
    """Published when one worker-backed domain changes availability."""

    domain: str
    state: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class WorkerMessageReceivedEvent:
    """Published when a worker emits a protocol event or result."""

    domain: str
    kind: str
    type: str
    request_id: str | None
    payload: dict[str, Any]
```

Add both names to `events.py` `__all__`.

In `yoyopod/core/__init__.py`, add these entries to `_PUBLIC_EXPORTS`:

```python
"WorkerDomainStateChangedEvent": (
    "yoyopod.core.events",
    "WorkerDomainStateChangedEvent",
),
"WorkerMessageReceivedEvent": (
    "yoyopod.core.events",
    "WorkerMessageReceivedEvent",
),
```

- [ ] **Step 4: Implement supervisor dataclasses**

Create `yoyopod/core/workers/supervisor.py`:

```python
"""Supervisor for named YoYoPod worker processes."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from yoyopod.core.bus import Bus
from yoyopod.core.events import (
    WorkerDomainStateChangedEvent,
    WorkerMessageReceivedEvent,
)
from yoyopod.core.scheduler import MainThreadScheduler
from yoyopod.core.workers.process import WorkerProcessConfig, WorkerProcessRuntime
from yoyopod.core.workers.protocol import WorkerEnvelope


@dataclass(slots=True)
class _WorkerSlot:
    config: WorkerProcessConfig
    runtime: WorkerProcessRuntime | None = None
    state: str = "stopped"
    restart_count: int = 0
    next_restart_at: float = 0.0
    request_deadlines: dict[str, float] = field(default_factory=dict)
    request_timeouts: int = 0
    last_reason: str = ""
```

- [ ] **Step 5: Implement supervisor lifecycle**

Append:

```python
class WorkerSupervisor:
    """Own worker lifecycle while publishing only on the supervisor main thread."""

    def __init__(
        self,
        *,
        scheduler: MainThreadScheduler,
        bus: Bus,
        restart_backoff_seconds: float = 1.0,
        max_restarts: int = 3,
    ) -> None:
        self._scheduler = scheduler
        self._bus = bus
        self._restart_backoff_seconds = max(0.0, restart_backoff_seconds)
        self._max_restarts = max(0, max_restarts)
        self._workers: dict[str, _WorkerSlot] = {}

    def register(self, domain: str, config: WorkerProcessConfig) -> None:
        """Register one worker domain before it is started."""

        if domain in self._workers:
            raise ValueError(f"worker domain {domain!r} is already registered")
        self._workers[domain] = _WorkerSlot(config=config)

    def start(self, domain: str) -> None:
        """Start one worker domain."""

        slot = self._workers[domain]
        runtime = WorkerProcessRuntime(slot.config)
        runtime.start()
        slot.runtime = runtime
        self._set_state(domain, slot, "running", "started")

    def stop_all(self, *, grace_seconds: float = 1.0) -> None:
        """Stop all registered workers with bounded waits."""

        for domain, slot in self._workers.items():
            if slot.runtime is not None:
                slot.runtime.stop(grace_seconds=grace_seconds)
            self._set_state(domain, slot, "stopped", "stop_all")
```

- [ ] **Step 6: Implement poll, messages, and timeouts**

Append:

```python
    def poll(self, *, monotonic_now: float | None = None) -> int:
        """Advance worker state without blocking."""

        now = time.monotonic() if monotonic_now is None else monotonic_now
        processed = 0
        for domain, slot in self._workers.items():
            runtime = slot.runtime
            if runtime is None:
                continue
            messages = runtime.drain_messages()
            processed += len(messages)
            for message in messages:
                if message.request_id is not None:
                    slot.request_deadlines.pop(message.request_id, None)
                self._bus.publish(
                    WorkerMessageReceivedEvent(
                        domain=domain,
                        kind=message.kind,
                        type=message.type,
                        request_id=message.request_id,
                        payload=message.payload,
                    )
                )
            self._expire_requests(domain, slot, now=now)
            if not runtime.running and slot.state == "running":
                self._handle_exit(domain, slot, now=now)
            if slot.state == "degraded" and slot.next_restart_at > 0.0 and now >= slot.next_restart_at:
                self._restart_if_allowed(domain, slot, now=now)
        return processed

    def send_request(
        self,
        domain: str,
        *,
        type: str,
        payload: dict[str, object],
        request_id: str,
        timeout_seconds: float,
    ) -> bool:
        """Send one request and remember its timeout."""

        slot = self._workers[domain]
        runtime = slot.runtime
        if runtime is None:
            return False
        sent = runtime.send_command(
            type=type,
            payload=payload,
            request_id=request_id,
            timestamp_ms=int(time.time() * 1000),
            deadline_ms=int(max(0.0, timeout_seconds) * 1000),
        )
        if sent:
            slot.request_deadlines[request_id] = time.monotonic() + max(0.0, timeout_seconds)
        return sent

    def drain_worker_messages(self, domain: str) -> list[WorkerEnvelope]:
        """Testing helper for messages that have not yet been consumed by poll."""

        runtime = self._workers[domain].runtime
        return [] if runtime is None else runtime.drain_messages()

    def wait_until_exited(self, domain: str, *, timeout_seconds: float) -> bool:
        """Testing helper that waits for one worker process to exit."""

        runtime = self._workers[domain].runtime
        return True if runtime is None else runtime.wait_until_exited(timeout_seconds=timeout_seconds)
```

- [ ] **Step 7: Implement state transitions and snapshots**

Append:

```python
    def snapshot(self) -> dict[str, dict[str, object]]:
        """Return status-ready worker health data."""

        result: dict[str, dict[str, object]] = {}
        for domain, slot in self._workers.items():
            process_snapshot = slot.runtime.snapshot() if slot.runtime is not None else None
            result[domain] = {
                "state": slot.state,
                "restart_count": slot.restart_count,
                "next_restart_at": slot.next_restart_at,
                "last_reason": slot.last_reason,
                "pending_requests": len(slot.request_deadlines),
                "request_timeouts": slot.request_timeouts,
                "running": process_snapshot.running if process_snapshot is not None else False,
                "pid": process_snapshot.pid if process_snapshot is not None else None,
                "received_messages": (
                    process_snapshot.received_messages if process_snapshot is not None else 0
                ),
                "protocol_errors": (
                    process_snapshot.protocol_errors if process_snapshot is not None else 0
                ),
                "dropped_messages": (
                    process_snapshot.dropped_messages if process_snapshot is not None else 0
                ),
            }
        return result

    def _expire_requests(self, domain: str, slot: _WorkerSlot, *, now: float) -> None:
        expired = [
            request_id
            for request_id, deadline in slot.request_deadlines.items()
            if deadline <= now
        ]
        for request_id in expired:
            slot.request_deadlines.pop(request_id, None)
            slot.request_timeouts += 1
            if slot.runtime is not None:
                slot.runtime.send_command(
                    type=f"{domain}.cancel",
                    payload={"request_id": request_id},
                    request_id=request_id,
                    timestamp_ms=int(time.time() * 1000),
                    deadline_ms=1000,
                )

    def _handle_exit(self, domain: str, slot: _WorkerSlot, *, now: float) -> None:
        slot.next_restart_at = now + self._restart_backoff_seconds
        self._set_state(domain, slot, "degraded", "process_exited")

    def _restart_if_allowed(self, domain: str, slot: _WorkerSlot, *, now: float) -> None:
        if slot.restart_count >= self._max_restarts:
            slot.next_restart_at = 0.0
            self._set_state(domain, slot, "disabled", "max_restarts_exceeded")
            return
        slot.restart_count += 1
        self.start(domain)

    def _set_state(self, domain: str, slot: _WorkerSlot, state: str, reason: str) -> None:
        if slot.state == state and slot.last_reason == reason:
            return
        slot.state = state
        slot.last_reason = reason
        self._bus.publish(
            WorkerDomainStateChangedEvent(domain=domain, state=state, reason=reason)
        )
```

- [ ] **Step 8: Export supervisor**

Update `yoyopod/core/workers/__init__.py`:

```python
from yoyopod.core.workers.supervisor import WorkerSupervisor
```

Add `"WorkerSupervisor"` to `__all__`.

- [ ] **Step 9: Run supervisor tests**

Run:

```bash
uv run pytest tests/core/workers/test_protocol.py tests/core/workers/test_process.py tests/core/workers/test_supervisor.py -q
```

Expected: all tests pass.

- [ ] **Step 10: Commit**

Run:

```bash
git add yoyopod/core/events.py yoyopod/core/__init__.py yoyopod/core/workers/__init__.py yoyopod/core/workers/supervisor.py tests/core/workers/test_supervisor.py
git commit -m "feat: add worker supervisor"
```

---

## Task 7: Integrate Worker Supervisor Into App and Loop

**Files:**

- Modify: `yoyopod/core/application.py`
- Modify: `yoyopod/core/loop.py`
- Modify: `yoyopod/core/status.py`
- Test: `tests/core/workers/test_supervisor.py`
- Test: `tests/core/test_runtime_loop_metrics.py`

- [ ] **Step 1: Add app integration tests**

Append to `tests/core/workers/test_supervisor.py`:

```python
from yoyopod.core.application import YoyoPodApp
from yoyopod.core.workers.supervisor import WorkerSupervisor


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
```

Append to `tests/core/test_runtime_loop_metrics.py`:

```python
def test_runtime_loop_polls_worker_supervisor() -> None:
    app = YoyoPodApp()
    calls = []
    app.worker_supervisor = SimpleNamespace(
        poll=lambda: calls.append("poll") or 0,
        snapshot=lambda: {},
    )
    app.app_state_runtime = SimpleNamespace(get_state_name=lambda: "idle")
    app.call_interruption_policy = SimpleNamespace(music_interrupted_by_call=False)

    app.runtime_loop.run_iteration(
        monotonic_now=10.0,
        current_time=20.0,
        last_screen_update=20.0,
        screen_update_interval=1.0,
    )

    assert calls == ["poll"]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/core/workers/test_supervisor.py tests/core/test_runtime_loop_metrics.py -q
```

Expected: failure because app does not own `worker_supervisor` and loop does not poll it.

- [ ] **Step 3: Add app-owned supervisor**

In `yoyopod/core/application.py`, import:

```python
from yoyopod.core.workers import WorkerSupervisor
```

In `YoyoPodApp.__init__()`, after `self.runtime_metrics = RuntimeMetricsStore()`, add:

```python
self.worker_supervisor = WorkerSupervisor(scheduler=self.scheduler, bus=self.bus)
```

- [ ] **Step 4: Stop workers before legacy resources**

In `YoyoPodApp.stop()`, before `_teardown_registered_integrations()`, add:

```python
self.worker_supervisor.stop_all(grace_seconds=1.0)
```

This stop is safe when no workers are registered.

- [ ] **Step 5: Poll workers in runtime loop**

In `RuntimeLoopService.run_iteration()`, after the `main_thread_actions` span and before manager recovery, add:

```python
self._measure_blocking_span(
    "worker_poll",
    self.app.worker_supervisor.poll,
)
```

- [ ] **Step 6: Expose worker snapshot in status and timing snapshot**

In `RuntimeStatusService.get_status()`, add:

```python
"workers": self.app.worker_supervisor.snapshot(),
```

In `RuntimeLoopService.timing_snapshot()`, add:

```python
"runtime_worker_count": len(self.app.worker_supervisor.snapshot()),
```

- [ ] **Step 7: Run tests**

Run:

```bash
uv run pytest tests/core/workers/test_supervisor.py tests/core/test_runtime_loop_metrics.py tests/core/test_runtime_metrics.py -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

Run:

```bash
git add yoyopod/core/application.py yoyopod/core/loop.py yoyopod/core/status.py tests/core/workers/test_supervisor.py tests/core/test_runtime_loop_metrics.py
git commit -m "feat: integrate worker supervisor with runtime"
```

---

## Task 8: Diagnostics Workflow Documentation

**Files:**

- Modify: `docs/PI_PROFILING_WORKFLOW.md`
- Test: documentation review by command output

- [ ] **Step 1: Add target-hardware profiling section**

Add this section to `docs/PI_PROFILING_WORKFLOW.md`:

```markdown
## Runtime Hybrid Phase 0 Baseline

Use this before moving voice or network into sidecar workers. The goal is to capture responsiveness and PSS/RSS with the current single-supervisor runtime.

### Enable responsiveness captures

```bash
export YOYOPOD_RESPONSIVENESS_WATCHDOG_ENABLED=true
export YOYOPOD_RESPONSIVENESS_STALL_THRESHOLD_SECONDS=5
export YOYOPOD_RESPONSIVENESS_RECENT_INPUT_WINDOW_SECONDS=3
```

### Start the dev lane

```bash
yoyopod remote mode activate dev
yoyopod remote sync --branch <branch>
yoyopod remote status
```

### Capture status snapshots

Run this before the mixed soak, during voice activity, during network reconnect, and after the soak:

```bash
yoyopod remote logs --lines 200
```

In the JSON status or captured diagnostics, record these fields:

- `responsiveness_input_to_action_p95_ms`
- `responsiveness_action_to_visible_p95_ms`
- `runtime_loop_gap_seconds`
- `runtime_main_thread_drain_seconds`
- `runtime_blocking_span_name`
- `runtime_blocking_span_seconds`
- `process_memory_rss_kb`
- `process_memory_pss_kb`
- `workers`

### One-hour mixed soak notes

During the soak, exercise:

- idle screen wake/sleep
- music navigation and playback
- incoming or simulated VoIP state changes
- voice command path with current local settings
- cellular/network reconnect or status polling
- low-risk power/status screen navigation

The acceptance target for the pre-worker baseline is not pass/fail. The goal is to identify top stalls and memory pressure before Phase 2 and Phase 3.
```

- [ ] **Step 2: Verify docs render as plain Markdown**

Run:

```bash
Get-Content docs/PI_PROFILING_WORKFLOW.md | Select-String -Pattern "Runtime Hybrid Phase 0 Baseline"
```

Expected: the heading is printed once.

- [ ] **Step 3: Commit**

Run:

```bash
git add docs/PI_PROFILING_WORKFLOW.md
git commit -m "docs: add runtime hybrid profiling workflow"
```

---

## Task 9: Final Verification

**Files:**

- Verify all files changed by Tasks 1-8.

- [ ] **Step 1: Run focused tests**

Run:

```bash
uv run pytest tests/core/test_runtime_metrics.py tests/core/test_runtime_loop_metrics.py tests/core/diagnostics/test_memory.py tests/core/workers/test_protocol.py tests/core/workers/test_process.py tests/core/workers/test_supervisor.py -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run required quality gate**

Run:

```bash
uv run python scripts/quality.py gate
```

Expected: `result=passed`.

- [ ] **Step 3: Run full test suite**

Run:

```bash
uv run pytest -q
```

Expected: full suite passes. On Windows, compare any failures against current known Windows-only failures before changing code. Do not ignore new failures in files touched by this plan.

- [ ] **Step 4: Inspect final status**

Run:

```bash
git status --short
```

Expected: clean working tree after all task commits.

---

## Self-Review

**Spec coverage:** This plan implements Phase 0 and Phase 1 from the design spec. It covers input-to-action latency, action-to-visible-refresh latency, loop/drain/blocking diagnostics, PSS/RSS snapshots, NDJSON worker envelopes, bounded queues, malformed message handling, worker stop bounds, restart/degraded state, cancellation on timeout, worker status, and fake-worker tests.

**Explicitly deferred:** Go cloud voice worker, Python network sidecar, cloud provider API shape, temp audio payload lifetime, worker binary packaging, and VoIP sidecar decision. These require follow-up plans after this foundation is merged and measured.

**Type consistency:** The plan consistently uses `WorkerEnvelope`, `WorkerProcessConfig`, `WorkerProcessRuntime`, `WorkerSupervisor`, `WorkerDomainStateChangedEvent`, and `WorkerMessageReceivedEvent`.

**No new runtime dependencies:** Memory diagnostics use procfs only. Worker runtime uses stdlib process/thread/queue primitives. IPC stays NDJSON over stdio.

**Commit discipline:** Each task ends with a narrow commit. Before the final branch handoff, run both required repo checks: `uv run python scripts/quality.py gate` and `uv run pytest -q`.
