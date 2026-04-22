"""Responsiveness watchdog and diagnostics capture helpers."""

from __future__ import annotations

import faulthandler
import json
import signal
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, TextIO

from yoyopod.core import RUNTIME_REQUIRED_CONFIG_FILES
from yoyopod.core.logging import get_subsystem_logger

app_logger = get_subsystem_logger("app")

StatusProvider = Callable[[], Mapping[str, object]]
CaptureCallback = Callable[["ResponsivenessWatchdogDecision", Mapping[str, object]], None]
TimeProvider = Callable[[], float]


@dataclass(frozen=True, slots=True)
class ResponsivenessWatchdogDecision:
    """Normalized watchdog decision describing why evidence should be captured."""

    reason: str
    suspected_scope: str
    summary: str


def evaluate_responsiveness_status(
    status: Mapping[str, object],
    *,
    stall_threshold_seconds: float,
    recent_input_window_seconds: float,
) -> ResponsivenessWatchdogDecision | None:
    """Return one capture decision when the runtime looks unresponsive."""

    loop_age = _coerce_float(status.get("loop_heartbeat_age_seconds"))
    if loop_age is None or loop_age < max(0.1, stall_threshold_seconds):
        return None

    input_age = _coerce_float(status.get("input_activity_age_seconds"))
    handled_input_age = _coerce_float(status.get("handled_input_activity_age_seconds"))
    lvgl_age = _coerce_float(status.get("lvgl_pump_age_seconds"))
    pending_scheduler_tasks = max(0, _coerce_int(status.get("pending_scheduler_tasks")) or 0)
    pending_events = max(0, _coerce_int(status.get("pending_bus_events")) or 0)
    last_input_action = str(status.get("last_input_action") or "none")
    last_handled_input_action = str(status.get("last_handled_input_action") or "none")
    current_screen = str(status.get("current_screen") or "none")
    current_state = str(status.get("state") or "unknown")
    display_backend = str(status.get("display_backend") or "unknown")

    recent_input = input_age is not None and input_age <= max(0.1, recent_input_window_seconds)
    handled_input_lagging = recent_input and (
        handled_input_age is None
        or handled_input_age >= stall_threshold_seconds
        or handled_input_age > (input_age + 0.5)
    )
    if handled_input_lagging:
        handled_text = "never" if handled_input_age is None else f"{handled_input_age:.1f}s"
        return ResponsivenessWatchdogDecision(
            reason="coordinator_stall_after_input",
            suspected_scope="input_to_runtime_handoff",
            summary=(
                "Loop heartbeat stalled at "
                f"{loop_age:.1f}s while input stayed alive (input_age={input_age:.1f}s, "
                f"handled_input_age={handled_text}, last_input={last_input_action}, "
                f"last_handled_input={last_handled_input_action}, "
                f"pending_scheduler_tasks={pending_scheduler_tasks}, pending_events={pending_events}, "
                f"screen={current_screen}, state={current_state})"
            ),
        )

    if pending_scheduler_tasks > 0 or pending_events > 0:
        return ResponsivenessWatchdogDecision(
            reason="coordinator_stall_with_pending_work",
            suspected_scope="runtime",
            summary=(
                "Loop heartbeat stalled at "
                f"{loop_age:.1f}s with queued work pending "
                f"(scheduler_tasks={pending_scheduler_tasks}, events={pending_events}, "
                f"screen={current_screen}, state={current_state})"
            ),
        )

    if display_backend == "lvgl" and lvgl_age is not None and lvgl_age >= stall_threshold_seconds:
        return ResponsivenessWatchdogDecision(
            reason="ui_and_runtime_stall",
            suspected_scope="ui_and_runtime",
            summary=(
                "Loop and LVGL pump both stopped advancing "
                f"(loop_age={loop_age:.1f}s, lvgl_age={lvgl_age:.1f}s, "
                f"screen={current_screen}, state={current_state})"
            ),
        )

    return ResponsivenessWatchdogDecision(
        reason="broad_runtime_stall",
        suspected_scope="runtime",
        summary=(
            "Loop heartbeat stalled without fresh input evidence "
            f"(loop_age={loop_age:.1f}s, screen={current_screen}, state={current_state})"
        ),
    )


class ResponsivenessWatchdog:
    """Background observer that captures evidence when the app loop stops advancing."""

    def __init__(
        self,
        *,
        status_provider: StatusProvider,
        capture_callback: CaptureCallback,
        stall_threshold_seconds: float,
        recent_input_window_seconds: float,
        poll_interval_seconds: float,
        capture_cooldown_seconds: float,
        time_provider: TimeProvider | None = None,
    ) -> None:
        self._status_provider = status_provider
        self._capture_callback = capture_callback
        self._stall_threshold_seconds = max(0.1, float(stall_threshold_seconds))
        self._recent_input_window_seconds = max(
            0.1,
            float(recent_input_window_seconds),
        )
        self._poll_interval_seconds = max(0.1, float(poll_interval_seconds))
        self._capture_cooldown_seconds = max(0.0, float(capture_cooldown_seconds))
        self._time_provider = time.monotonic if time_provider is None else time_provider
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._stall_active = False
        self._last_capture_at = 0.0

    def start(self) -> None:
        """Start the background watchdog thread once."""

        if self._thread is not None:
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="responsiveness-watchdog",
        )
        self._thread.start()
        app_logger.info(
            "Responsiveness watchdog armed (threshold={}s, poll={}s)",
            self._stall_threshold_seconds,
            self._poll_interval_seconds,
        )

    def stop(self, *, timeout_seconds: float = 2.0) -> None:
        """Stop the background watchdog thread."""

        thread = self._thread
        if thread is None:
            return

        self._stop_event.set()
        thread.join(timeout=max(0.1, timeout_seconds))
        self._thread = None
        app_logger.info("Responsiveness watchdog stopped")

    def poll_once(self) -> ResponsivenessWatchdogDecision | None:
        """Run one check cycle and capture evidence when needed."""

        try:
            status = self._status_provider()
        except Exception:
            app_logger.exception("Responsiveness watchdog failed to collect status")
            return None

        decision = evaluate_responsiveness_status(
            status,
            stall_threshold_seconds=self._stall_threshold_seconds,
            recent_input_window_seconds=self._recent_input_window_seconds,
        )
        if decision is None:
            self._stall_active = False
            return None

        now = self._time_provider()
        if self._stall_active:
            return None
        if (
            self._last_capture_at > 0.0
            and (now - self._last_capture_at) < self._capture_cooldown_seconds
        ):
            self._stall_active = True
            return None

        self._stall_active = True
        self._last_capture_at = now
        try:
            self._capture_callback(decision, status)
        except Exception:
            app_logger.exception("Responsiveness watchdog capture failed")
        return decision

    def _run(self) -> None:
        """Background watchdog loop."""

        while not self._stop_event.wait(self._poll_interval_seconds):
            self.poll_once()


def _signal_name(signum: int) -> str:
    """Return a stable signal name for diagnostics logs."""

    try:
        return signal.Signals(signum).name
    except ValueError:
        return str(signum)


def _json_safe(value: object) -> object:
    """Normalize runtime state into JSON-safe values for snapshots."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            pass
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _build_runtime_snapshot_payload(
    *,
    app: object,
    source: str,
    trigger: str,
    captured_at: datetime | None = None,
    capture_mode: str | None = None,
    reason: str | None = None,
    suspected_scope: str | None = None,
    summary: str | None = None,
    status: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build one JSON-safe runtime snapshot payload for logs or evidence files."""

    payload: dict[str, object] = {
        "captured_at": (captured_at or datetime.now(timezone.utc)).isoformat(),
        "source": source,
        "trigger": trigger,
    }
    if capture_mode is not None:
        payload["capture_mode"] = capture_mode
    if reason is not None:
        payload["reason"] = reason
    if suspected_scope is not None:
        payload["suspected_scope"] = suspected_scope
    if summary is not None:
        payload["summary"] = summary

    snapshot_status = status
    if snapshot_status is None:
        get_status = getattr(app, "get_status", None)
        if callable(get_status):
            try:
                snapshot_status = get_status()
            except Exception as exc:
                payload["status_error"] = str(exc)
        else:
            payload["status_error"] = "app does not expose get_status()"

    if snapshot_status is not None:
        payload["status"] = _json_safe(snapshot_status)

    return payload


def _log_signal_snapshot(
    *,
    app: object,
    app_log: Any,
    signal_name: str,
    prefer_readback: bool,
) -> None:
    """Emit one structured runtime snapshot to the error log on demand."""

    payload = _build_runtime_snapshot_payload(
        app=app,
        source="signal_snapshot",
        trigger=signal_name,
        capture_mode="readback-first" if prefer_readback else "shadow-first",
        status=None,
    )
    payload["signal"] = signal_name
    app_log.error("Freeze diagnostics snapshot: {}", json.dumps(payload, sort_keys=True))


def _log_setup_failure_guidance(app_log: Any) -> None:
    """Log shared bootstrap guidance when app setup fails."""

    app_log.error("Check that:")
    for relative_path in RUNTIME_REQUIRED_CONFIG_FILES:
        app_log.error(f"  - {relative_path.as_posix()} exists")
    app_log.error(
        "  - data/people/contacts.yaml can be created from config/people/contacts.seed.yaml"
    )
    app_log.error("  - liblinphone is installed and the native shim is built")
    app_log.error("  - mpv is installed and the configured music backend can start")
    app_log.error(
        "  - Whisplay production runs have a working LVGL shim and do not rely on PIL or simulation fallback"
    )


def _resolve_responsiveness_capture_dir(app: object) -> Path:
    """Resolve the configured directory for automatic watchdog captures."""

    app_settings = getattr(app, "app_settings", None)
    diagnostics = getattr(app_settings, "diagnostics", None)
    raw_capture_dir = getattr(diagnostics, "responsiveness_capture_dir", "logs/responsiveness")
    capture_dir = Path(str(raw_capture_dir))
    if not capture_dir.is_absolute():
        capture_dir = Path.cwd() / capture_dir
    return capture_dir


def _append_traceback_dump(
    *,
    dump_path: Path,
    app_log: Any,
    header: str,
) -> bool:
    """Write one all-thread traceback dump to the provided file path."""

    dump_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with dump_path.open("a", encoding="utf-8", buffering=1) as dump_stream:
            dump_stream.write(f"{header}\n")
            faulthandler.dump_traceback(file=dump_stream, all_threads=True)
            dump_stream.write("\n")
    except OSError as exc:
        app_log.warning("Failed to write traceback dump {}: {}", dump_path, exc)
        return False
    return True


def _capture_responsiveness_watchdog_evidence(
    *,
    app: object,
    app_log: Any,
    error_log_path: Path,
    decision: ResponsivenessWatchdogDecision,
    status: Mapping[str, object],
) -> None:
    """Persist one automatic responsiveness capture and announce where it landed."""

    captured_at = datetime.now(timezone.utc)
    payload = _build_runtime_snapshot_payload(
        app=app,
        source="responsiveness_watchdog",
        trigger=decision.reason,
        captured_at=captured_at,
        reason=decision.reason,
        suspected_scope=decision.suspected_scope,
        summary=decision.summary,
        status=status,
    )
    capture_dir = _resolve_responsiveness_capture_dir(app)
    capture_dir.mkdir(parents=True, exist_ok=True)

    captured_at_iso = payload["captured_at"]
    timestamp = captured_at.strftime("%Y%m%dT%H%M%SZ")
    stem = f"{timestamp}-{decision.reason}"
    snapshot_path = capture_dir / f"{stem}.json"
    snapshot_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    traceback_path = capture_dir / f"{stem}.traceback.txt"
    _append_traceback_dump(
        dump_path=traceback_path,
        app_log=app_log,
        header=(
            f"=== Responsiveness watchdog capture at {captured_at_iso} "
            f"reason={decision.reason} scope={decision.suspected_scope} ==="
        ),
    )

    record_capture = getattr(app, "record_responsiveness_capture", None)
    artifacts = {
        "snapshot": str(snapshot_path),
        "traceback": str(traceback_path),
        "error_log": str(error_log_path),
    }
    if callable(record_capture):
        record_capture(
            captured_at=time.monotonic(),
            reason=decision.reason,
            suspected_scope=decision.suspected_scope,
            summary=decision.summary,
            artifacts=artifacts,
        )

    app_log.error(
        "Responsiveness watchdog captured evidence: {}",
        json.dumps(
            {
                "captured_at": captured_at_iso,
                "reason": decision.reason,
                "suspected_scope": decision.suspected_scope,
                "summary": decision.summary,
                "snapshot_path": str(snapshot_path),
                "traceback_path": str(traceback_path),
                "loop_heartbeat_age_seconds": status.get("loop_heartbeat_age_seconds"),
                "input_activity_age_seconds": status.get("input_activity_age_seconds"),
                "handled_input_activity_age_seconds": status.get(
                    "handled_input_activity_age_seconds"
                ),
                "current_screen": status.get("current_screen"),
                "state": status.get("state"),
            },
            sort_keys=True,
        ),
    )


def _install_traceback_dump_handlers(
    *,
    signals: tuple[int, ...],
    dump_path: Path,
    app_log: Any,
) -> tuple[TextIO | None, tuple[int, ...]]:
    """Chain all-thread traceback dumps onto the screenshot signals."""

    if not signals:
        return None, ()

    dump_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        dump_stream = dump_path.open("a", encoding="utf-8", buffering=1)
    except OSError as exc:
        app_log.warning("Failed to open traceback dump log {}: {}", dump_path, exc)
        return None, ()

    installed: list[int] = []
    for signum in signals:
        try:
            faulthandler.register(signum, file=dump_stream, all_threads=True, chain=True)
        except (OSError, RuntimeError, ValueError) as exc:
            app_log.warning(
                "Failed to arm traceback dump for {}: {}",
                _signal_name(signum),
                exc,
            )
            continue
        installed.append(signum)

    if not installed:
        dump_stream.close()
        return None, ()

    app_log.info(
        "Freeze traceback dumps armed for {} -> {}",
        ", ".join(_signal_name(signum) for signum in installed),
        dump_path,
    )
    return dump_stream, tuple(installed)


def _uninstall_traceback_dump_handlers(
    *,
    signals: tuple[int, ...],
    dump_stream: TextIO | None,
) -> None:
    """Best-effort faulthandler cleanup on process exit."""

    for signum in signals:
        try:
            faulthandler.unregister(signum)
        except (OSError, RuntimeError, ValueError):
            continue

    if dump_stream is not None:
        dump_stream.close()


def _coerce_float(value: object) -> float | None:
    """Best-effort float conversion for status values."""

    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: object) -> int | None:
    """Best-effort integer conversion for status values."""

    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "ResponsivenessWatchdog",
    "ResponsivenessWatchdogDecision",
    "_capture_responsiveness_watchdog_evidence",
    "_install_traceback_dump_handlers",
    "_log_setup_failure_guidance",
    "_log_signal_snapshot",
    "_signal_name",
    "_uninstall_traceback_dump_handlers",
    "evaluate_responsiveness_status",
]
