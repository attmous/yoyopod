"""VoIP validation subcommand."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Callable, Protocol, cast

import typer

from yoyopod_cli.common import REPO_ROOT, configure_logging, resolve_config_dir
from yoyopod_cli.pi.support.call_models import CallState, RegistrationState, VoIPConfig
from yoyopod_cli.pi.validate._common import _CheckResult, _print_summary
from yoyopod_cli.pi.validate.service_env import load_service_env_file, resolve_service_env_file

# ---------------------------------------------------------------------------
# VoIP check helper
# ---------------------------------------------------------------------------


def _voip_check(config_dir: Path, registration_timeout: float) -> _CheckResult:
    """Validate Rust VoIP startup and SIP registration."""
    from yoyopod_cli.config import ConfigManager
    from yoyopod_cli.pi.rust_voip_runtime import build_rust_voip_manager

    config_manager = ConfigManager(config_dir=str(config_dir))
    voip_config = VoIPConfig.from_config_manager(config_manager)

    if not voip_config.sip_identity:
        return _CheckResult(
            name="voip",
            status="fail",
            details="sip_identity is empty in config/communication/calling.yaml",
        )

    try:
        manager = build_rust_voip_manager(str(config_dir))
    except RuntimeError as exc:
        return _CheckResult(name="voip", status="fail", details=str(exc))
    try:
        if not manager.start():
            return _CheckResult(
                name="voip",
                status="fail",
                details="VoIP manager failed to start",
            )

        deadline = time.time() + registration_timeout
        last_status = manager.get_status()

        while time.time() < deadline:
            manager.iterate()
            last_status = manager.get_status()
            if last_status["registered"]:
                return _CheckResult(
                    name="voip",
                    status="pass",
                    details=(
                        f"registered={last_status['registered']}, "
                        f"state={last_status['registration_state']}, "
                        f"identity={last_status['sip_identity']}"
                    ),
                )

            if last_status["registration_state"] == "failed":
                break

            time.sleep(0.5)

        return _CheckResult(
            name="voip",
            status="fail",
            details=(
                f"registration timed out or failed; "
                f"state={last_status['registration_state']}, "
                f"identity={last_status['sip_identity']}"
            ),
        )
    except Exception as exc:
        return _CheckResult(name="voip", status="fail", details=str(exc))
    finally:
        manager.stop()


# ---------------------------------------------------------------------------
# VoIP drill helpers for the flattened validation suite
# ---------------------------------------------------------------------------

_CONNECTED_CALL_STATES: set[str] = set()  # populated lazily below
_ACTIVE_CALL_STATES: set[str] = set()  # populated lazily below


def _lazy_connected_call_states() -> set[str]:
    global _CONNECTED_CALL_STATES
    if not _CONNECTED_CALL_STATES:
        _CONNECTED_CALL_STATES = {CallState.CONNECTED.value, CallState.STREAMS_RUNNING.value}
    return _CONNECTED_CALL_STATES


def _lazy_active_call_states() -> set[str]:
    global _ACTIVE_CALL_STATES
    if not _ACTIVE_CALL_STATES:
        _ACTIVE_CALL_STATES = {
            CallState.CONNECTED.value,
            CallState.STREAMS_RUNNING.value,
            CallState.PAUSED.value,
            CallState.PAUSED_BY_REMOTE.value,
            CallState.UPDATED_BY_REMOTE.value,
        }
    return _ACTIVE_CALL_STATES


class _VoIPManagerLike(Protocol):
    """Minimal manager surface needed by the drill helpers."""

    config: Any
    running: bool

    def start(self) -> bool: ...

    def stop(self) -> None: ...

    def iterate(self) -> int: ...

    def get_status(self) -> dict[str, Any]: ...

    def get_iterate_metrics(self) -> object | None: ...

    def on_registration_change(
        self,
        callback: Callable[[Any], None],
    ) -> None: ...

    def on_runtime_snapshot_change(
        self,
        callback: Callable[[Any], None],
    ) -> None: ...

    def make_call(self, sip_address: str, contact_name: str | None = None) -> bool: ...

    def hangup(self) -> bool: ...

    def get_call_duration(self) -> int: ...


@dataclass(slots=True)
class _DrillResult:
    """One drill outcome and the evidence written to disk."""

    drill: str
    passed: bool
    reason: str
    artifact_dir: Path
    summary_path: Path
    timeline_path: Path
    extras: dict[str, object] = field(default_factory=dict)

    @property
    def status(self) -> str:
        return "pass" if self.passed else "fail"


class _VoIPDrillRecorder:
    """Collect state changes and periodic samples into one timestamped artifact bundle."""

    def __init__(
        self,
        *,
        drill: str,
        config: Any,
        artifacts_dir: str,
        metadata: dict[str, object] | None = None,
        sample_interval_seconds: float = 1.0,
    ) -> None:
        self.drill = drill
        self.config = config
        self.metadata = metadata or {}
        self.started_at_monotonic = time.monotonic()
        self.started_at_unix = time.time()
        self.started_at_iso = self._iso_time(self.started_at_unix)
        self.sample_interval_seconds = max(0.2, sample_interval_seconds)
        self._next_sample_at = self.started_at_monotonic
        artifact_root = self._resolve_artifacts_dir(artifacts_dir)
        run_label = datetime.fromtimestamp(
            self.started_at_unix,
            timezone.utc,
        ).strftime("%Y%m%dT%H%M%SZ")
        self.artifact_dir = artifact_root / f"{drill}-{run_label}"
        self.timeline_path = self.artifact_dir / "timeline.jsonl"
        self.summary_path = self.artifact_dir / "summary.json"
        self.events: list[dict[str, object]] = []
        self.registration_states: list[str] = []
        self.call_states: list[str] = []

    @staticmethod
    def _resolve_artifacts_dir(artifacts_dir: str) -> Path:
        candidate = Path(artifacts_dir)
        if not candidate.is_absolute():
            candidate = REPO_ROOT / candidate
        return candidate

    @staticmethod
    def _iso_time(timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")

    def attach(self, manager: _VoIPManagerLike) -> None:
        manager.on_registration_change(self._on_registration_change)
        manager.on_runtime_snapshot_change(self._on_runtime_snapshot_change)

    def _emit(self, kind: str, **payload: object) -> None:
        event = {
            "timestamp": self._iso_time(time.time()),
            "elapsed_seconds": round(max(0.0, time.monotonic() - self.started_at_monotonic), 3),
            "kind": kind,
            **payload,
        }
        self.events.append(event)

    def note(self, message: str) -> None:
        self._emit("note", message=message)

    def checkpoint(self, name: str, **payload: object) -> None:
        self._emit("checkpoint", name=name, **payload)

    def record_command(
        self,
        *,
        phase: str,
        command: str,
        returncode: int,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self._emit(
            "command",
            phase=phase,
            command=command,
            returncode=returncode,
            stdout=stdout.strip(),
            stderr=stderr.strip(),
        )

    def sample(self, manager: _VoIPManagerLike, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now < self._next_sample_at:
            return
        self._emit("sample", status=self._status_snapshot(manager))
        self._next_sample_at = now + self.sample_interval_seconds

    def finalize(
        self,
        *,
        passed: bool,
        reason: str,
        manager: _VoIPManagerLike,
        extras: dict[str, object] | None = None,
    ) -> _DrillResult:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        with self.timeline_path.open("w", encoding="utf-8") as handle:
            for event in self.events:
                handle.write(json.dumps(event, sort_keys=True) + "\n")

        finished_at_unix = time.time()
        resolved_extras: dict[str, object] = extras or {}
        summary = {
            "drill": self.drill,
            "status": "pass" if passed else "fail",
            "reason": reason,
            "started_at": self.started_at_iso,
            "finished_at": self._iso_time(finished_at_unix),
            "duration_seconds": round(
                max(0.0, time.monotonic() - self.started_at_monotonic),
                3,
            ),
            "artifact_dir": str(self.artifact_dir),
            "timeline_path": str(self.timeline_path),
            "final_status": self._status_snapshot(manager),
            "registration_states": self.registration_states,
            "call_states": self.call_states,
            "config": {
                "sip_server": getattr(self.config, "sip_server", ""),
                "sip_identity": getattr(self.config, "sip_identity", ""),
                "iterate_interval_ms": getattr(self.config, "iterate_interval_ms", 0),
            },
            "metadata": self.metadata,
            "extras": resolved_extras,
        }
        with self.summary_path.open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2, sort_keys=True)
            handle.write("\n")

        return _DrillResult(
            drill=self.drill,
            passed=passed,
            reason=reason,
            artifact_dir=self.artifact_dir,
            summary_path=self.summary_path,
            timeline_path=self.timeline_path,
            extras=resolved_extras,
        )

    def _status_snapshot(self, manager: _VoIPManagerLike) -> dict[str, object]:
        status = dict(manager.get_status())
        snapshot: dict[str, object] = {
            "running": bool(status.get("running", False)),
            "registered": bool(status.get("registered", False)),
            "registration_state": str(status.get("registration_state", "")),
            "call_state": str(status.get("call_state", "")),
        }
        get_call_duration = getattr(manager, "get_call_duration", None)
        if callable(get_call_duration):
            snapshot["call_duration_seconds"] = int(get_call_duration())
        metrics = manager.get_iterate_metrics()
        if metrics is not None:
            snapshot["iterate_metrics"] = {
                "native_ms": round(
                    float(getattr(metrics, "native_duration_seconds", 0.0)) * 1000.0,
                    1,
                ),
                "event_drain_ms": round(
                    float(getattr(metrics, "event_drain_duration_seconds", 0.0)) * 1000.0,
                    1,
                ),
                "total_ms": round(
                    float(getattr(metrics, "total_duration_seconds", 0.0)) * 1000.0,
                    1,
                ),
                "drained_events": int(getattr(metrics, "drained_events", 0)),
            }
        return snapshot

    def _on_registration_change(self, state: Any) -> None:
        self.registration_states.append(state.value)
        self._emit("registration", state=state.value)

    def _on_runtime_snapshot_change(self, snapshot: Any) -> None:
        state = getattr(snapshot, "call_state", None)
        value = getattr(state, "value", str(state or ""))
        if not value:
            return
        self.call_states.append(value)
        self._emit("call_state", state=value)


def _build_voip_manager_for_drill(config_dir: str) -> _VoIPManagerLike:
    from loguru import logger

    from yoyopod_cli.pi.rust_voip_runtime import build_rust_voip_manager

    try:
        return cast(_VoIPManagerLike, build_rust_voip_manager(config_dir))
    except RuntimeError as exc:
        logger.error(str(exc))
        raise typer.Exit(code=1)


def _iterate_interval_seconds(manager: _VoIPManagerLike) -> float:
    return max(0.01, float(getattr(manager.config, "iterate_interval_ms", 20)) / 1000.0)


def _status_is_registered(status: dict[str, object]) -> bool:
    return bool(status.get("registered")) and (
        str(status.get("registration_state")) == RegistrationState.OK.value
    )


def _wait_for_registration_ok(
    manager: _VoIPManagerLike,
    recorder: _VoIPDrillRecorder,
    *,
    timeout: float,
) -> tuple[bool, float]:
    started_at = time.monotonic()
    deadline = started_at + timeout
    interval = _iterate_interval_seconds(manager)
    while time.monotonic() <= deadline:
        manager.iterate()
        recorder.sample(manager)
        if _status_is_registered(manager.get_status()):
            return True, max(0.0, time.monotonic() - started_at)
        time.sleep(interval)
    recorder.sample(manager, force=True)
    return False, max(0.0, time.monotonic() - started_at)


def _wait_for_registration_drop(
    manager: _VoIPManagerLike,
    recorder: _VoIPDrillRecorder,
    *,
    timeout: float,
) -> tuple[bool, str, float]:
    started_at = time.monotonic()
    deadline = started_at + timeout
    interval = _iterate_interval_seconds(manager)
    while time.monotonic() <= deadline:
        manager.iterate()
        recorder.sample(manager)
        status = manager.get_status()
        if not _status_is_registered(status):
            return (
                True,
                str(status.get("registration_state", "")),
                max(0.0, time.monotonic() - started_at),
            )
        time.sleep(interval)
    recorder.sample(manager, force=True)
    return (
        False,
        str(manager.get_status().get("registration_state", "")),
        max(0.0, time.monotonic() - started_at),
    )


def _hold_registration_ok(
    manager: _VoIPManagerLike,
    recorder: _VoIPDrillRecorder,
    *,
    hold_seconds: float,
) -> tuple[bool, str]:
    deadline = time.monotonic() + hold_seconds
    interval = _iterate_interval_seconds(manager)
    while time.monotonic() <= deadline:
        manager.iterate()
        recorder.sample(manager)
        status = manager.get_status()
        if not _status_is_registered(status):
            return False, str(status.get("registration_state", ""))
        time.sleep(interval)
    recorder.sample(manager, force=True)
    return True, RegistrationState.OK.value


def _wait_for_call_connection(
    manager: _VoIPManagerLike,
    recorder: _VoIPDrillRecorder,
    *,
    timeout: float,
) -> tuple[bool, str, float]:
    started_at = time.monotonic()
    deadline = started_at + timeout
    interval = _iterate_interval_seconds(manager)
    terminal_states = {
        CallState.RELEASED.value,
        CallState.END.value,
        CallState.ERROR.value,
    }
    connected_states = _lazy_connected_call_states()
    observed_started_call = False
    while time.monotonic() <= deadline:
        manager.iterate()
        recorder.sample(manager)
        status = manager.get_status()
        call_state = str(status.get("call_state", ""))
        if call_state in connected_states:
            return True, call_state, max(0.0, time.monotonic() - started_at)
        if call_state != CallState.IDLE.value:
            observed_started_call = True
        if call_state == CallState.IDLE.value and observed_started_call:
            return False, call_state, max(0.0, time.monotonic() - started_at)
        if call_state in terminal_states:
            return False, call_state, max(0.0, time.monotonic() - started_at)
        time.sleep(interval)
    recorder.sample(manager, force=True)
    return (
        False,
        str(manager.get_status().get("call_state", "")),
        max(0.0, time.monotonic() - started_at),
    )


def _hold_call_connected(
    manager: _VoIPManagerLike,
    recorder: _VoIPDrillRecorder,
    *,
    soak_seconds: float,
) -> tuple[bool, str]:
    deadline = time.monotonic() + soak_seconds
    interval = _iterate_interval_seconds(manager)
    active_states = _lazy_active_call_states()
    while time.monotonic() <= deadline:
        manager.iterate()
        recorder.sample(manager)
        status = manager.get_status()
        if not _status_is_registered(status):
            return False, f"registration_state={status.get('registration_state', '')}"
        call_state = str(status.get("call_state", ""))
        if call_state not in active_states:
            return False, f"call_state={call_state}"
        time.sleep(interval)
    recorder.sample(manager, force=True)
    return True, ""


def _wait_for_call_end(
    manager: _VoIPManagerLike,
    recorder: _VoIPDrillRecorder,
    *,
    timeout: float,
) -> tuple[bool, str, float]:
    started_at = time.monotonic()
    deadline = started_at + timeout
    interval = _iterate_interval_seconds(manager)
    terminal_states = {
        CallState.IDLE.value,
        CallState.RELEASED.value,
        CallState.END.value,
        CallState.ERROR.value,
    }
    while time.monotonic() <= deadline:
        manager.iterate()
        recorder.sample(manager)
        status = manager.get_status()
        call_state = str(status.get("call_state", ""))
        if call_state in terminal_states:
            return True, call_state, max(0.0, time.monotonic() - started_at)
        time.sleep(interval)
    recorder.sample(manager, force=True)
    return (
        False,
        str(manager.get_status().get("call_state", "")),
        max(0.0, time.monotonic() - started_at),
    )


def _run_shell_hook(
    *,
    recorder: _VoIPDrillRecorder,
    phase: str,
    command: str,
) -> bool:
    """Run an operator-supplied outage hook.

    The reconnect drill treats --drop-command/--restore-command as trusted operator input
    for a local diagnostic workflow on the device, so shell execution is intentional here.
    """
    completed = subprocess.run(
        command,
        shell=True,
        check=False,
        capture_output=True,
        text=True,
    )
    recorder.record_command(
        phase=phase,
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    return completed.returncode == 0


def _print_drill_result(result: _DrillResult) -> None:
    print("")
    print(f"VoIP drill result: {result.drill}")
    print("=" * 48)
    print(f"status={result.status}")
    print(f"reason={result.reason}")
    for key, value in sorted(result.extras.items()):
        print(f"{key}={value}")
    print(f"artifact_dir={result.artifact_dir}")
    print(f"summary={result.summary_path}")
    print(f"timeline={result.timeline_path}")


# ---------------------------------------------------------------------------
# VoIP soak private runners (converted from @voip_app.command bodies)
# ---------------------------------------------------------------------------


def _run_quick_voip_check(config_dir: str, registration_timeout: float) -> None:
    """Run the quick VoIP registration validation (no soak)."""
    config_path = resolve_config_dir(config_dir)
    results = [_voip_check(config_path, registration_timeout)]
    _print_summary("voip", results)
    if any(result.status == "fail" for result in results):
        raise typer.Exit(code=1)


def _run_voip_registration_stability(
    config_dir: str,
    registration_timeout: float,
    hold_seconds: float,
    artifacts_dir: str,
    sample_interval: float,
) -> None:
    """Hold SIP registration open long enough to catch immediate flapping on hardware."""
    from loguru import logger

    manager = _build_voip_manager_for_drill(config_dir)
    recorder = _VoIPDrillRecorder(
        drill="registration-stability",
        config=manager.config,
        artifacts_dir=artifacts_dir,
        metadata={
            "registration_timeout": registration_timeout,
            "hold_seconds": hold_seconds,
        },
        sample_interval_seconds=sample_interval,
    )
    recorder.attach(manager)

    try:
        if not manager.start():
            result = recorder.finalize(
                passed=False,
                reason="VoIP manager failed to start",
                manager=manager,
            )
            _print_drill_result(result)
            raise typer.Exit(code=1)

        logger.info("Waiting for SIP registration to stabilize")
        registered, registration_seconds = _wait_for_registration_ok(
            manager,
            recorder,
            timeout=registration_timeout,
        )
        if not registered:
            result = recorder.finalize(
                passed=False,
                reason="Registration never reached OK",
                manager=manager,
                extras={"registration_wait_seconds": round(registration_seconds, 3)},
            )
            _print_drill_result(result)
            raise typer.Exit(code=1)

        recorder.checkpoint(
            "registration_ok",
            registration_wait_seconds=round(registration_seconds, 3),
        )
        stable, failed_state = _hold_registration_ok(
            manager,
            recorder,
            hold_seconds=hold_seconds,
        )
        result = recorder.finalize(
            passed=stable,
            reason=(
                f"Registration stayed OK for {hold_seconds:.1f}s"
                if stable
                else f"Registration left OK during stability hold: {failed_state}"
            ),
            manager=manager,
            extras={
                "registration_wait_seconds": round(registration_seconds, 3),
                "hold_seconds": hold_seconds,
                "failed_state": failed_state,
            },
        )
        _print_drill_result(result)
        if not stable:
            raise typer.Exit(code=1)
    finally:
        manager.stop()


def _run_voip_reconnect_drill(
    config_dir: str,
    registration_timeout: float,
    disconnect_seconds: float,
    drop_detect_timeout: float,
    recovery_timeout: float,
    drop_command: str,
    restore_command: str,
    artifacts_dir: str,
    sample_interval: float,
) -> None:
    """Verify that SIP registration drops and then recovers after a short network wobble."""
    from loguru import logger

    manager = _build_voip_manager_for_drill(config_dir)
    recorder = _VoIPDrillRecorder(
        drill="reconnect-drill",
        config=manager.config,
        artifacts_dir=artifacts_dir,
        metadata={
            "registration_timeout": registration_timeout,
            "disconnect_seconds": disconnect_seconds,
            "drop_detect_timeout": drop_detect_timeout,
            "recovery_timeout": recovery_timeout,
            "drop_command": drop_command,
            "restore_command": restore_command,
        },
        sample_interval_seconds=sample_interval,
    )
    recorder.attach(manager)

    try:
        if not manager.start():
            result = recorder.finalize(
                passed=False,
                reason="VoIP manager failed to start",
                manager=manager,
            )
            _print_drill_result(result)
            raise typer.Exit(code=1)

        registered, registration_seconds = _wait_for_registration_ok(
            manager,
            recorder,
            timeout=registration_timeout,
        )
        if not registered:
            result = recorder.finalize(
                passed=False,
                reason="Initial registration never reached OK",
                manager=manager,
                extras={"registration_wait_seconds": round(registration_seconds, 3)},
            )
            _print_drill_result(result)
            raise typer.Exit(code=1)

        recorder.checkpoint(
            "initial_registration_ok",
            registration_wait_seconds=round(registration_seconds, 3),
        )
        if drop_command:
            logger.info("Running network drop hook")
            if not _run_shell_hook(recorder=recorder, phase="drop", command=drop_command):
                result = recorder.finalize(
                    passed=False,
                    reason="The configured network drop command failed",
                    manager=manager,
                )
                _print_drill_result(result)
                raise typer.Exit(code=1)
        else:
            message = (
                f"Drop network connectivity now for about {disconnect_seconds:.1f}s, "
                "then restore it. The drill is recording registration loss and recovery."
            )
            logger.info(message)
            recorder.note(message)

        outage_started_at = time.monotonic()
        outage_deadline = outage_started_at + disconnect_seconds
        drop_observed = False
        drop_state = RegistrationState.OK.value
        first_drop_wait_seconds: float | None = None
        while time.monotonic() <= outage_deadline:
            manager.iterate()
            recorder.sample(manager)
            status = manager.get_status()
            if not _status_is_registered(status):
                drop_observed = True
                drop_state = str(status.get("registration_state", ""))
                if first_drop_wait_seconds is None:
                    first_drop_wait_seconds = max(0.0, time.monotonic() - outage_started_at)
            time.sleep(_iterate_interval_seconds(manager))

        if restore_command:
            logger.info("Running network restore hook")
            if not _run_shell_hook(recorder=recorder, phase="restore", command=restore_command):
                result = recorder.finalize(
                    passed=False,
                    reason="The configured network restore command failed",
                    manager=manager,
                    extras={"drop_observed": drop_observed, "drop_state": drop_state},
                )
                _print_drill_result(result)
                raise typer.Exit(code=1)
        elif drop_command:
            logger.info("Restore network connectivity now so SIP registration can recover")
            recorder.note("Restore network connectivity now so SIP registration can recover.")

        if not drop_observed:
            drop_observed, drop_state, drop_wait_seconds = _wait_for_registration_drop(
                manager,
                recorder,
                timeout=drop_detect_timeout,
            )
        else:
            assert first_drop_wait_seconds is not None
            drop_wait_seconds = first_drop_wait_seconds

        if not drop_observed:
            result = recorder.finalize(
                passed=False,
                reason="Registration never left OK during the reconnect drill",
                manager=manager,
                extras={
                    "registration_wait_seconds": round(registration_seconds, 3),
                    "drop_wait_seconds": round(drop_wait_seconds, 3),
                    "drop_state": drop_state,
                },
            )
            _print_drill_result(result)
            raise typer.Exit(code=1)

        recorder.checkpoint(
            "registration_dropped",
            drop_wait_seconds=round(drop_wait_seconds, 3),
            drop_state=drop_state,
        )
        recovered, recovery_seconds = _wait_for_registration_ok(
            manager,
            recorder,
            timeout=recovery_timeout,
        )
        result = recorder.finalize(
            passed=recovered,
            reason=(
                "Registration recovered after the temporary outage"
                if recovered
                else "Registration did not recover after the temporary outage"
            ),
            manager=manager,
            extras={
                "registration_wait_seconds": round(registration_seconds, 3),
                "drop_wait_seconds": round(drop_wait_seconds, 3),
                "drop_state": drop_state,
                "recovery_wait_seconds": round(recovery_seconds, 3),
            },
        )
        _print_drill_result(result)
        if not recovered:
            raise typer.Exit(code=1)
    finally:
        manager.stop()


def _run_voip_call_soak(
    config_dir: str,
    target: str,
    contact_name: str,
    registration_timeout: float,
    connect_timeout: float,
    soak_seconds: float,
    hangup_timeout: float,
    artifacts_dir: str,
    sample_interval: float,
) -> None:
    """Place one real call, wait for connection, and hold it long enough to catch drift."""
    from loguru import logger

    manager = _build_voip_manager_for_drill(config_dir)
    recorder = _VoIPDrillRecorder(
        drill="call-soak",
        config=manager.config,
        artifacts_dir=artifacts_dir,
        metadata={
            "target": target,
            "contact_name": contact_name,
            "registration_timeout": registration_timeout,
            "connect_timeout": connect_timeout,
            "soak_seconds": soak_seconds,
            "hangup_timeout": hangup_timeout,
        },
        sample_interval_seconds=sample_interval,
    )
    recorder.attach(manager)

    try:
        if not manager.start():
            result = recorder.finalize(
                passed=False,
                reason="VoIP manager failed to start",
                manager=manager,
            )
            _print_drill_result(result)
            raise typer.Exit(code=1)

        registered, registration_seconds = _wait_for_registration_ok(
            manager,
            recorder,
            timeout=registration_timeout,
        )
        if not registered:
            result = recorder.finalize(
                passed=False,
                reason="Registration never reached OK before the call soak",
                manager=manager,
                extras={"registration_wait_seconds": round(registration_seconds, 3)},
            )
            _print_drill_result(result)
            raise typer.Exit(code=1)

        if not manager.make_call(target, contact_name or None):
            result = recorder.finalize(
                passed=False,
                reason=f"Failed to initiate call to {target}",
                manager=manager,
                extras={"registration_wait_seconds": round(registration_seconds, 3)},
            )
            _print_drill_result(result)
            raise typer.Exit(code=1)

        logger.info("Waiting for the call to connect: {}", target)
        connected, connected_state, connect_seconds = _wait_for_call_connection(
            manager,
            recorder,
            timeout=connect_timeout,
        )
        if not connected:
            result = recorder.finalize(
                passed=False,
                reason=f"Call never reached a connected state (last_state={connected_state})",
                manager=manager,
                extras={
                    "target": target,
                    "registration_wait_seconds": round(registration_seconds, 3),
                    "connect_wait_seconds": round(connect_seconds, 3),
                    "last_call_state": connected_state,
                },
            )
            _print_drill_result(result)
            raise typer.Exit(code=1)

        recorder.checkpoint(
            "call_connected",
            target=target,
            connect_wait_seconds=round(connect_seconds, 3),
            connected_state=connected_state,
        )
        soaked, soak_failure = _hold_call_connected(
            manager,
            recorder,
            soak_seconds=soak_seconds,
        )
        cleanup_reason = "cleanup_skipped"
        if manager.hangup():
            hangup_ok, hangup_state, hangup_seconds = _wait_for_call_end(
                manager,
                recorder,
                timeout=hangup_timeout,
            )
            cleanup_reason = (
                f"hangup_wait_seconds={round(hangup_seconds, 3)} last_state={hangup_state}"
                if not hangup_ok
                else "hangup_clean"
            )
        result = recorder.finalize(
            passed=soaked,
            reason=(
                f"Call stayed connected for {soak_seconds:.1f}s"
                if soaked
                else f"Call soak failed: {soak_failure}"
            ),
            manager=manager,
            extras={
                "target": target,
                "registration_wait_seconds": round(registration_seconds, 3),
                "connect_wait_seconds": round(connect_seconds, 3),
                "soak_seconds": soak_seconds,
                "cleanup": cleanup_reason,
            },
        )
        _print_drill_result(result)
        if not soaked:
            raise typer.Exit(code=1)
    finally:
        manager.stop()


# ---------------------------------------------------------------------------
# Subcommand
# ---------------------------------------------------------------------------


def voip(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    env_file: Annotated[
        str,
        typer.Option(
            "--env-file",
            help="Service EnvironmentFile to load before resolving VoIP settings.",
        ),
    ] = "/etc/default/yoyopod-dev",
    registration_timeout: Annotated[
        float, typer.Option("--registration-timeout", help="Registration timeout in seconds.")
    ] = 90.0,
    soak: Annotated[
        str,
        typer.Option(
            "--soak",
            help="Optional soak mode: registration | reconnect | call",
        ),
    ] = "",
    # registration-soak options
    hold_seconds: Annotated[
        float,
        typer.Option(
            "--hold-seconds", help="How long SIP registration must remain OK after startup."
        ),
    ] = 60.0,
    # reconnect-soak options
    disconnect_seconds: Annotated[
        float,
        typer.Option(
            "--disconnect-seconds", help="How long the temporary network outage should last."
        ),
    ] = 8.0,
    drop_detect_timeout: Annotated[
        float,
        typer.Option(
            "--drop-detect-timeout",
            help="How long to wait for registration to leave OK after the outage starts.",
        ),
    ] = 20.0,
    recovery_timeout: Annotated[
        float,
        typer.Option(
            "--recovery-timeout",
            help="How long to wait for SIP registration to recover after the outage.",
        ),
    ] = 45.0,
    drop_command: Annotated[
        str,
        typer.Option(
            "--drop-command",
            help="Optional shell command that intentionally drops network connectivity on the Pi.",
        ),
    ] = "",
    restore_command: Annotated[
        str,
        typer.Option(
            "--restore-command",
            help="Optional shell command that restores network connectivity on the Pi.",
        ),
    ] = "",
    # call-soak options
    soak_target: Annotated[
        str,
        typer.Option(
            "--soak-target",
            help="SIP address to call for the call soak drill, for example sip:echo@example.com.",
        ),
    ] = "",
    soak_contact_name: Annotated[
        str,
        typer.Option(
            "--soak-contact-name",
            help="Optional contact label used for log output while making the call.",
        ),
    ] = "",
    soak_seconds: Annotated[
        float,
        typer.Option(
            "--soak-seconds", help="How long the call must remain connected once media is up."
        ),
    ] = 300.0,
    connect_timeout: Annotated[
        float,
        typer.Option(
            "--connect-timeout",
            help="How long to wait for the target call to reach a connected media state.",
        ),
    ] = 60.0,
    hangup_timeout: Annotated[
        float,
        typer.Option(
            "--hangup-timeout",
            help="How long to wait for the call to tear down cleanly after the soak.",
        ),
    ] = 15.0,
    # shared soak options
    artifacts_dir: Annotated[
        str,
        typer.Option(
            "--artifacts-dir", help="Directory where timestamped drill artifacts should be written."
        ),
    ] = "logs/voip-validation",
    sample_interval: Annotated[
        float,
        typer.Option(
            "--sample-interval",
            help="How often to capture periodic status samples into the timeline.",
        ),
    ] = 1.0,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """VoIP validation: quick check (default) or soak drill (--soak registration|reconnect|call)."""
    configure_logging(verbose)
    if env_file.strip():
        load_service_env_file(resolve_service_env_file(env_file))
    if not soak:
        return _run_quick_voip_check(config_dir, registration_timeout)
    if soak == "registration":
        return _run_voip_registration_stability(
            config_dir,
            registration_timeout,
            hold_seconds,
            artifacts_dir,
            sample_interval,
        )
    if soak == "reconnect":
        return _run_voip_reconnect_drill(
            config_dir,
            registration_timeout,
            disconnect_seconds,
            drop_detect_timeout,
            recovery_timeout,
            drop_command,
            restore_command,
            artifacts_dir,
            sample_interval,
        )
    if soak == "call":
        if not soak_target:
            raise typer.BadParameter("--soak call requires --soak-target")
        return _run_voip_call_soak(
            config_dir,
            soak_target,
            soak_contact_name,
            registration_timeout,
            connect_timeout,
            soak_seconds,
            hangup_timeout,
            artifacts_dir,
            sample_interval,
        )
    raise typer.BadParameter(
        f"unknown --soak value: {soak!r}; expected registration, reconnect, or call"
    )
