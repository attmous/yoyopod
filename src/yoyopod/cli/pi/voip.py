"""src/yoyopod/cli/pi/voip.py — VoIP diagnostic and reliability drill commands."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

import typer

from yoyopod.cli.common import REPO_ROOT, configure_logging, resolve_config_dir
from yoyopod.communication.models import CallState, RegistrationState

voip_app = typer.Typer(
    name="voip",
    help="VoIP diagnostic and reliability drill commands.",
    no_args_is_help=True,
)

_CONNECTED_CALL_STATES = {CallState.CONNECTED.value, CallState.STREAMS_RUNNING.value}


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
        callback: Callable[[RegistrationState], None],
    ) -> None: ...

    def on_call_state_change(
        self,
        callback: Callable[[CallState], None],
    ) -> None: ...

    def on_incoming_call(
        self,
        callback: Callable[[str, str], None],
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
        manager.on_call_state_change(self._on_call_state_change)

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

    def _on_registration_change(self, state: RegistrationState) -> None:
        self.registration_states.append(state.value)
        self._emit("registration", state=state.value)

    def _on_call_state_change(self, state: CallState) -> None:
        self.call_states.append(state.value)
        self._emit("call_state", state=state.value)


def _build_voip_manager(config_dir: str) -> _VoIPManagerLike:
    from loguru import logger

    from yoyopod.communication import VoIPConfig, VoIPManager
    from yoyopod.communication.integrations.liblinphone_binding import LiblinphoneBinding
    from yoyopod.config import ConfigManager

    if LiblinphoneBinding.try_load() is None:
        logger.error(
            "Liblinphone shim is unavailable. Build it first with yoyoctl build liblinphone."
        )
        raise typer.Exit(code=1)

    config_path = resolve_config_dir(config_dir)
    config_manager = ConfigManager(config_dir=str(config_path))
    voip_config = VoIPConfig.from_config_manager(config_manager)
    return VoIPManager(voip_config)


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
    while time.monotonic() <= deadline:
        manager.iterate()
        recorder.sample(manager)
        status = manager.get_status()
        call_state = str(status.get("call_state", ""))
        if call_state in _CONNECTED_CALL_STATES:
            return True, call_state, max(0.0, time.monotonic() - started_at)
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
    while time.monotonic() <= deadline:
        manager.iterate()
        recorder.sample(manager)
        status = manager.get_status()
        if not _status_is_registered(status):
            return False, f"registration_state={status.get('registration_state', '')}"
        call_state = str(status.get("call_state", ""))
        if call_state not in _CONNECTED_CALL_STATES:
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


def _print_result(result: _DrillResult) -> None:
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


@voip_app.command()
def check(
    config_dir: str = typer.Option(
        "config",
        "--config-dir",
        help="Configuration directory to use.",
    ),
) -> None:
    """Run a verbose SIP registration check against the Liblinphone backend."""
    from loguru import logger

    configure_logging(verbose=True)

    logger.info("=" * 60)
    logger.info("Liblinphone Registration Test")
    logger.info("=" * 60)

    voip_manager = _build_voip_manager(config_dir)
    voip_config = voip_manager.config

    logger.info(f"SIP Server: {voip_config.sip_server}")
    logger.info(f"SIP Username: {voip_config.sip_username}")
    logger.info(f"SIP Identity: {voip_config.sip_identity}")
    logger.info(f"Transport: {voip_config.transport}")
    logger.info(f"STUN Server: {voip_config.stun_server}")
    logger.info(f"File transfer server: {voip_config.file_transfer_server_url or 'unset'}")

    registration_states: list[RegistrationState] = []
    voip_manager.on_registration_change(lambda state: registration_states.append(state))

    try:
        if not voip_manager.start():
            logger.error("Failed to start VoIP manager")
            raise typer.Exit(code=1)

        deadline = time.time() + 10.0
        while time.time() < deadline:
            voip_manager.iterate()
            status = voip_manager.get_status()
            if status["registered"]:
                logger.success("Registration successful")
                logger.success(f"State history: {[state.value for state in registration_states]}")
                return
            time.sleep(max(0.01, voip_config.iterate_interval_ms / 1000.0))

        status = voip_manager.get_status()
        logger.error("Registration failed or timed out")
        logger.error(f"State: {status['registration_state']}")
        logger.error(f"History: {[state.value for state in registration_states]}")
        raise typer.Exit(code=1)
    finally:
        voip_manager.stop()


@voip_app.command()
def debug(
    config_dir: str = typer.Option(
        "config",
        "--config-dir",
        help="Configuration directory to use.",
    ),
) -> None:
    """Monitor for incoming SIP calls with verbose logging."""
    from loguru import logger

    configure_logging(verbose=True)

    logger.info("=" * 60)
    logger.info("Incoming Call Debug Test")
    logger.info("=" * 60)

    voip_manager = _build_voip_manager(config_dir)
    voip_config = voip_manager.config
    incoming_calls: list[tuple[str, str]] = []

    def on_incoming_call(caller_address: str, caller_name: str) -> None:
        logger.success("=" * 60)
        logger.success("INCOMING CALL CALLBACK FIRED")
        logger.success(f"  Address: {caller_address}")
        logger.success(f"  Name: {caller_name}")
        logger.success("=" * 60)
        incoming_calls.append((caller_address, caller_name))

    voip_manager.on_incoming_call(on_incoming_call)

    try:
        if not voip_manager.start():
            logger.error("Failed to start VoIP manager")
            raise typer.Exit(code=1)

        logger.info(f"Waiting for incoming calls on {voip_config.sip_identity}")
        logger.info("Press Ctrl+C to exit")

        while True:
            voip_manager.iterate()
            time.sleep(max(0.01, voip_config.iterate_interval_ms / 1000.0))
    except KeyboardInterrupt:
        logger.info("Interrupted")
    finally:
        voip_manager.stop()
        logger.info(f"Total incoming calls detected: {len(incoming_calls)}")
        for address, name in incoming_calls:
            logger.info(f"  - {name} ({address})")


@voip_app.command(name="registration-stability")
def registration_stability(
    config_dir: str = typer.Option(
        "config",
        "--config-dir",
        help="Configuration directory to use.",
    ),
    registration_timeout: float = typer.Option(
        30.0,
        "--registration-timeout",
        help="How long to wait for SIP registration to reach OK.",
    ),
    hold_seconds: float = typer.Option(
        60.0,
        "--hold-seconds",
        help="How long SIP registration must remain OK after startup.",
    ),
    artifacts_dir: str = typer.Option(
        "logs/voip-validation",
        "--artifacts-dir",
        help="Directory where timestamped drill artifacts should be written.",
    ),
    sample_interval: float = typer.Option(
        1.0,
        "--sample-interval",
        help="How often to capture periodic status samples into the timeline.",
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable DEBUG logging."),
) -> None:
    """Hold SIP registration open long enough to catch immediate flapping on hardware."""

    from loguru import logger

    configure_logging(verbose)
    manager = _build_voip_manager(config_dir)
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
            _print_result(result)
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
            _print_result(result)
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
        _print_result(result)
        if not stable:
            raise typer.Exit(code=1)
    finally:
        manager.stop()


@voip_app.command(name="reconnect-drill")
def reconnect_drill(
    config_dir: str = typer.Option(
        "config",
        "--config-dir",
        help="Configuration directory to use.",
    ),
    registration_timeout: float = typer.Option(
        30.0,
        "--registration-timeout",
        help="How long to wait for the initial SIP registration to reach OK.",
    ),
    disconnect_seconds: float = typer.Option(
        8.0,
        "--disconnect-seconds",
        help="How long the temporary network outage should last.",
    ),
    drop_detect_timeout: float = typer.Option(
        20.0,
        "--drop-detect-timeout",
        help="How long to wait for registration to leave OK after the outage starts.",
    ),
    recovery_timeout: float = typer.Option(
        45.0,
        "--recovery-timeout",
        help="How long to wait for SIP registration to recover after the outage.",
    ),
    drop_command: str = typer.Option(
        "",
        "--drop-command",
        help="Optional shell command that intentionally drops network connectivity on the Pi.",
    ),
    restore_command: str = typer.Option(
        "",
        "--restore-command",
        help="Optional shell command that restores network connectivity on the Pi.",
    ),
    artifacts_dir: str = typer.Option(
        "logs/voip-validation",
        "--artifacts-dir",
        help="Directory where timestamped drill artifacts should be written.",
    ),
    sample_interval: float = typer.Option(
        1.0,
        "--sample-interval",
        help="How often to capture periodic status samples into the timeline.",
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable DEBUG logging."),
) -> None:
    """Verify that SIP registration drops and then recovers after a short network wobble."""

    from loguru import logger

    configure_logging(verbose)
    manager = _build_voip_manager(config_dir)
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
            _print_result(result)
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
            _print_result(result)
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
                _print_result(result)
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
                _print_result(result)
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
            drop_wait_seconds = first_drop_wait_seconds or 0.0

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
            _print_result(result)
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
        _print_result(result)
        if not recovered:
            raise typer.Exit(code=1)
    finally:
        manager.stop()


@voip_app.command(name="call-soak")
def call_soak(
    target: str = typer.Option(
        ...,
        "--target",
        help="SIP address to call for the soak drill, for example sip:echo@example.com.",
    ),
    contact_name: str = typer.Option(
        "",
        "--contact-name",
        help="Optional contact label used for log output while making the call.",
    ),
    config_dir: str = typer.Option(
        "config",
        "--config-dir",
        help="Configuration directory to use.",
    ),
    registration_timeout: float = typer.Option(
        30.0,
        "--registration-timeout",
        help="How long to wait for SIP registration to reach OK before calling.",
    ),
    connect_timeout: float = typer.Option(
        60.0,
        "--connect-timeout",
        help="How long to wait for the target call to reach a connected media state.",
    ),
    soak_seconds: float = typer.Option(
        300.0,
        "--soak-seconds",
        help="How long the call must remain connected once media is up.",
    ),
    hangup_timeout: float = typer.Option(
        15.0,
        "--hangup-timeout",
        help="How long to wait for the call to tear down cleanly after the soak.",
    ),
    artifacts_dir: str = typer.Option(
        "logs/voip-validation",
        "--artifacts-dir",
        help="Directory where timestamped drill artifacts should be written.",
    ),
    sample_interval: float = typer.Option(
        1.0,
        "--sample-interval",
        help="How often to capture periodic status samples into the timeline.",
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable DEBUG logging."),
) -> None:
    """Place one real call, wait for connection, and hold it long enough to catch drift."""

    from loguru import logger

    configure_logging(verbose)
    manager = _build_voip_manager(config_dir)
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
            _print_result(result)
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
            _print_result(result)
            raise typer.Exit(code=1)

        if not manager.make_call(target, contact_name or None):
            result = recorder.finalize(
                passed=False,
                reason=f"Failed to initiate call to {target}",
                manager=manager,
                extras={"registration_wait_seconds": round(registration_seconds, 3)},
            )
            _print_result(result)
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
            _print_result(result)
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
        _print_result(result)
        if not soaked:
            raise typer.Exit(code=1)
    finally:
        manager.stop()
