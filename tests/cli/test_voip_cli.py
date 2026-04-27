"""Tests for the focused VoIP reliability drill commands."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("typer")

from typer.testing import CliRunner

from yoyopod_cli.pi_validate import voip as voip_cli
from yoyopod_cli.pi_validate import app as pi_validate_app
import yoyopod_cli.pi_voip as voip_check_cli
from yoyopod.integrations.call.models import CallState, RegistrationState

runner = CliRunner()


class FakeClock:
    """Deterministic clock for time-driven drill loops."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def time(self) -> float:
        return 1_700_000_000.0 + self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(0.0, seconds)


class FakeVoIPManager:
    """Small manager double that can schedule registration and call transitions."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.config = SimpleNamespace(
            iterate_interval_ms=100,
            sip_server="sip.example.com",
            sip_username="alice",
            sip_identity="sip:alice@example.com",
            transport="udp",
            stun_server="stun.example.com",
            file_transfer_server_url="https://uploads.example.com",
        )
        self.running = False
        self.registered = False
        self.registration_state = RegistrationState.NONE
        self.call_state = CallState.IDLE
        self._registration_callbacks: list[object] = []
        self._call_state_callbacks: list[object] = []
        self._incoming_call_callbacks: list[object] = []
        self._scheduled: list[tuple[float, object]] = []
        self.call_connected_at: float | None = None
        self.start_result = True
        self.make_call_result = True

    def schedule_registration(self, delay_seconds: float, state: RegistrationState) -> None:
        self._scheduled.append((self.clock.now + delay_seconds, ("registration", state)))

    def schedule_call_state(self, delay_seconds: float, state: CallState) -> None:
        self._scheduled.append((self.clock.now + delay_seconds, ("call", state)))

    def on_registration_change(self, callback) -> None:
        self._registration_callbacks.append(callback)

    def on_call_state_change(self, callback) -> None:
        self._call_state_callbacks.append(callback)

    def on_incoming_call(self, callback) -> None:
        self._incoming_call_callbacks.append(callback)

    def start(self) -> bool:
        self.running = True
        return self.start_result

    def stop(self) -> None:
        self.running = False

    def iterate(self) -> int:
        drained = 0
        due = [item for item in self._scheduled if item[0] <= self.clock.now]
        self._scheduled = [item for item in self._scheduled if item[0] > self.clock.now]
        for _at, payload in sorted(due, key=lambda item: item[0]):
            drained += 1
            kind, state = payload
            if kind == "registration":
                self._set_registration(state)
            else:
                self._set_call_state(state)
        return drained

    def get_status(self) -> dict[str, object]:
        return {
            "running": self.running,
            "registered": self.registered,
            "registration_state": self.registration_state.value,
            "call_state": self.call_state.value,
        }

    def get_iterate_metrics(self) -> object | None:
        return SimpleNamespace(
            native_duration_seconds=0.01,
            event_drain_duration_seconds=0.0,
            total_duration_seconds=0.01,
            drained_events=0,
        )

    def make_call(self, sip_address: str, contact_name: str | None = None) -> bool:
        if not self.make_call_result:
            return False
        self._set_call_state(CallState.OUTGOING_RINGING)
        self.schedule_call_state(0.2, CallState.CONNECTED)
        return True

    def hangup(self) -> bool:
        self.schedule_call_state(0.1, CallState.END)
        return True

    def get_call_duration(self) -> int:
        if self.call_connected_at is None:
            return 0
        return int(max(0.0, self.clock.now - self.call_connected_at))

    def _set_registration(self, state: RegistrationState) -> None:
        self.registration_state = state
        self.registered = state == RegistrationState.OK
        for callback in self._registration_callbacks:
            callback(state)

    def _set_call_state(self, state: CallState) -> None:
        self.call_state = state
        if (
            state in {CallState.CONNECTED, CallState.STREAMS_RUNNING}
            and self.call_connected_at is None
        ):
            self.call_connected_at = self.clock.now
        if state in {CallState.END, CallState.RELEASED, CallState.IDLE, CallState.ERROR}:
            self.call_connected_at = None
        for callback in self._call_state_callbacks:
            callback(state)


def _patch_clock(monkeypatch: pytest.MonkeyPatch, clock: FakeClock) -> None:
    monkeypatch.setattr(voip_cli.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(voip_cli.time, "time", clock.time)
    monkeypatch.setattr(voip_cli.time, "sleep", clock.sleep)


def _run_dir(artifacts_dir: Path) -> Path:
    return next(artifacts_dir.iterdir())


def _load_summary(artifacts_dir: Path) -> dict[str, object]:
    run_dir = _run_dir(artifacts_dir)
    return json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))


def _load_timeline(artifacts_dir: Path) -> list[dict[str, object]]:
    run_dir = _run_dir(artifacts_dir)
    return [
        json.loads(line)
        for line in (run_dir / "timeline.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def test_registration_stability_writes_pass_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The registration drill should pass and persist a summary when SIP stays stable."""

    clock = FakeClock()
    manager = FakeVoIPManager(clock)
    manager.schedule_registration(0.2, RegistrationState.OK)
    _patch_clock(monkeypatch, clock)
    monkeypatch.setattr(voip_cli, "_build_voip_manager_for_drill", lambda _config_dir: manager)

    result = runner.invoke(
        pi_validate_app,
        [
            "voip",
            "--soak", "registration",
            "--registration-timeout",
            "1",
            "--hold-seconds",
            "1",
            "--sample-interval",
            "0.5",
            "--artifacts-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    summary = _load_summary(tmp_path)
    assert summary["status"] == "pass"
    assert summary["registration_states"] == ["ok"]
    assert summary["extras"]["hold_seconds"] == 1.0


def test_registration_stability_fails_when_registration_flaps_during_hold(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The registration drill should exit non-zero when registration leaves OK during the hold."""

    clock = FakeClock()
    manager = FakeVoIPManager(clock)
    manager.schedule_registration(0.1, RegistrationState.OK)
    manager.schedule_registration(0.4, RegistrationState.FAILED)
    _patch_clock(monkeypatch, clock)
    monkeypatch.setattr(voip_cli, "_build_voip_manager_for_drill", lambda _config_dir: manager)

    result = runner.invoke(
        pi_validate_app,
        [
            "voip",
            "--soak", "registration",
            "--registration-timeout",
            "1",
            "--hold-seconds",
            "1",
            "--artifacts-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    summary = _load_summary(tmp_path)
    assert summary["status"] == "fail"
    assert summary["reason"] == "Registration left OK during stability hold: failed"
    assert summary["extras"]["failed_state"] == "failed"


def test_registration_stability_fails_when_manager_start_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The registration drill should fail honestly when the VoIP manager never starts."""

    clock = FakeClock()
    manager = FakeVoIPManager(clock)
    manager.start_result = False
    _patch_clock(monkeypatch, clock)
    monkeypatch.setattr(voip_cli, "_build_voip_manager_for_drill", lambda _config_dir: manager)

    result = runner.invoke(
        pi_validate_app,
        [
            "voip",
            "--soak", "registration",
            "--registration-timeout",
            "1",
            "--hold-seconds",
            "1",
            "--artifacts-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    summary = _load_summary(tmp_path)
    assert summary["status"] == "fail"
    assert summary["reason"] == "VoIP manager failed to start"


def test_registration_stability_fails_when_registration_never_reaches_ok(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The registration drill should fail honestly when SIP never reaches OK."""

    clock = FakeClock()
    manager = FakeVoIPManager(clock)
    _patch_clock(monkeypatch, clock)
    monkeypatch.setattr(voip_cli, "_build_voip_manager_for_drill", lambda _config_dir: manager)

    result = runner.invoke(
        pi_validate_app,
        [
            "voip",
            "--soak", "registration",
            "--registration-timeout",
            "0.5",
            "--hold-seconds",
            "1",
            "--artifacts-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    summary = _load_summary(tmp_path)
    assert summary["status"] == "fail"
    assert summary["reason"] == "Registration never reached OK"
    assert summary["extras"]["registration_wait_seconds"] >= 0.5


def test_reconnect_drill_fails_when_registration_never_recovers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The reconnect drill should fail honestly when the network comes back but SIP does not."""

    clock = FakeClock()
    manager = FakeVoIPManager(clock)
    manager.schedule_registration(0.1, RegistrationState.OK)
    _patch_clock(monkeypatch, clock)
    monkeypatch.setattr(voip_cli, "_build_voip_manager_for_drill", lambda _config_dir: manager)

    def fake_hook(*, recorder, phase: str, command: str) -> bool:
        if phase == "drop":
            manager.schedule_registration(0.1, RegistrationState.FAILED)
        recorder.record_command(
            phase=phase,
            command=command,
            returncode=0,
            stdout="ok",
            stderr="",
        )
        return True

    monkeypatch.setattr(voip_cli, "_run_shell_hook", fake_hook)

    result = runner.invoke(
        pi_validate_app,
        [
            "voip",
            "--soak", "reconnect",
            "--registration-timeout",
            "1",
            "--disconnect-seconds",
            "0.4",
            "--drop-detect-timeout",
            "0.5",
            "--recovery-timeout",
            "0.5",
            "--drop-command",
            "drop-net",
            "--restore-command",
            "restore-net",
            "--artifacts-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    summary = _load_summary(tmp_path)
    assert summary["status"] == "fail"
    assert "did not recover" in summary["reason"]
    assert summary["extras"]["drop_state"] == "failed"
    assert summary["extras"]["drop_wait_seconds"] == pytest.approx(0.1)


def test_reconnect_drill_recovers_after_temporary_drop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The reconnect drill should pass when registration drops and then recovers."""

    clock = FakeClock()
    manager = FakeVoIPManager(clock)
    manager.schedule_registration(0.1, RegistrationState.OK)
    _patch_clock(monkeypatch, clock)
    monkeypatch.setattr(voip_cli, "_build_voip_manager_for_drill", lambda _config_dir: manager)

    def fake_hook(*, recorder, phase: str, command: str) -> bool:
        if phase == "drop":
            manager.schedule_registration(0.1, RegistrationState.FAILED)
        elif phase == "restore":
            manager.schedule_registration(0.1, RegistrationState.OK)
        recorder.record_command(
            phase=phase,
            command=command,
            returncode=0,
            stdout="ok",
            stderr="",
        )
        return True

    monkeypatch.setattr(voip_cli, "_run_shell_hook", fake_hook)

    result = runner.invoke(
        pi_validate_app,
        [
            "voip",
            "--soak", "reconnect",
            "--registration-timeout",
            "1",
            "--disconnect-seconds",
            "0.4",
            "--drop-detect-timeout",
            "0.5",
            "--recovery-timeout",
            "1",
            "--drop-command",
            "drop-net",
            "--restore-command",
            "restore-net",
            "--artifacts-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    summary = _load_summary(tmp_path)
    assert summary["status"] == "pass"
    assert summary["reason"] == "Registration recovered after the temporary outage"
    assert summary["extras"]["drop_state"] == "failed"
    assert summary["extras"]["drop_wait_seconds"] == pytest.approx(0.1)
    assert summary["registration_states"] == ["ok", "failed", "ok"]

    timeline = _load_timeline(tmp_path)
    assert any(event["kind"] == "command" and event["phase"] == "drop" for event in timeline)
    assert any(event["kind"] == "command" and event["phase"] == "restore" for event in timeline)
    assert any(
        event["kind"] == "checkpoint" and event.get("name") == "registration_dropped"
        for event in timeline
    )
    assert any(event["kind"] == "registration" and event.get("state") == "failed" for event in timeline)


def test_reconnect_drill_without_hooks_exercises_manual_operator_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The reconnect drill should still pass when an operator drops/restores connectivity manually."""

    clock = FakeClock()
    manager = FakeVoIPManager(clock)
    manager.schedule_registration(0.1, RegistrationState.OK)
    manager.schedule_registration(0.3, RegistrationState.FAILED)
    manager.schedule_registration(0.6, RegistrationState.OK)
    _patch_clock(monkeypatch, clock)
    monkeypatch.setattr(voip_cli, "_build_voip_manager_for_drill", lambda _config_dir: manager)

    result = runner.invoke(
        pi_validate_app,
        [
            "voip",
            "--soak", "reconnect",
            "--registration-timeout",
            "1",
            "--disconnect-seconds",
            "0.4",
            "--drop-detect-timeout",
            "0.5",
            "--recovery-timeout",
            "1",
            "--artifacts-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    summary = _load_summary(tmp_path)
    assert summary["status"] == "pass"
    assert summary["extras"]["drop_state"] == "failed"
    timeline = _load_timeline(tmp_path)
    notes = [event["message"] for event in timeline if event["kind"] == "note"]
    assert any("Drop network connectivity now" in message for message in notes)


@pytest.mark.parametrize(
    ("phase", "option"),
    [
        ("drop", "--drop-command"),
        ("restore", "--restore-command"),
    ],
)
def test_reconnect_drill_fails_when_hook_command_returns_non_zero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    phase: str,
    option: str,
) -> None:
    """The reconnect drill should fail honestly when an outage hook exits non-zero."""

    clock = FakeClock()
    manager = FakeVoIPManager(clock)
    manager.schedule_registration(0.1, RegistrationState.OK)
    _patch_clock(monkeypatch, clock)
    monkeypatch.setattr(voip_cli, "_build_voip_manager_for_drill", lambda _config_dir: manager)
    phase_under_test = phase

    def fake_hook(*, recorder, phase: str, command: str) -> bool:
        returncode = 23 if phase == phase_under_test else 0
        recorder.record_command(
            phase=phase,
            command=command,
            returncode=returncode,
            stdout="",
            stderr="boom" if returncode else "",
        )
        return returncode == 0

    monkeypatch.setattr(voip_cli, "_run_shell_hook", fake_hook)

    args = [
        "voip",
        "--soak", "reconnect",
        "--registration-timeout",
        "1",
        "--disconnect-seconds",
        "0.4",
        "--drop-detect-timeout",
        "0.5",
        "--recovery-timeout",
        "1",
    ]
    if phase == "restore":
        args.extend(["--drop-command", "drop-net"])
    args.extend(
        [
            option,
            f"{phase}-net",
            "--artifacts-dir",
            str(tmp_path),
        ]
    )

    result = runner.invoke(pi_validate_app, args)

    assert result.exit_code == 1
    summary = _load_summary(tmp_path)
    assert summary["status"] == "fail"
    assert summary["reason"] == f"The configured network {phase} command failed"
    timeline = _load_timeline(tmp_path)
    assert any(
        event["kind"] == "command"
        and event["phase"] == phase
        and event["returncode"] == 23
        for event in timeline
    )


@pytest.mark.parametrize(
    ("schedule_failure", "expected_reason"),
    [
        (
            lambda manager: manager.schedule_registration(0.2, RegistrationState.FAILED),
            "registration_state=failed",
        ),
        (
            lambda manager: manager.schedule_call_state(0.2, CallState.END),
            "call_state=end",
        ),
    ],
)
def test_hold_call_connected_returns_machine_friendly_failure_keys(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    schedule_failure,
    expected_reason: str,
) -> None:
    """The soak helper should report registration and call failures with stable key=value reasons."""

    clock = FakeClock()
    manager = FakeVoIPManager(clock)
    manager._set_registration(RegistrationState.OK)
    manager._set_call_state(CallState.CONNECTED)
    schedule_failure(manager)
    _patch_clock(monkeypatch, clock)

    recorder = voip_cli._VoIPDrillRecorder(
        drill="call-soak",
        config=manager.config,
        artifacts_dir=str(tmp_path),
    )
    recorder.attach(manager)

    soaked, reason = voip_cli._hold_call_connected(
        manager,
        recorder,
        soak_seconds=1.0,
    )

    assert soaked is False
    assert reason == expected_reason


def test_call_soak_writes_pass_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The call soak should pass when the call connects and remains up for the soak window."""

    clock = FakeClock()
    manager = FakeVoIPManager(clock)
    manager.schedule_registration(0.1, RegistrationState.OK)
    _patch_clock(monkeypatch, clock)
    monkeypatch.setattr(voip_cli, "_build_voip_manager_for_drill", lambda _config_dir: manager)

    result = runner.invoke(
        pi_validate_app,
        [
            "voip",
            "--soak", "call",
            "--soak-target",
            "sip:echo@example.com",
            "--registration-timeout",
            "1",
            "--connect-timeout",
            "1",
            "--soak-seconds",
            "1",
            "--hangup-timeout",
            "0.5",
            "--sample-interval",
            "0.5",
            "--artifacts-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    summary = _load_summary(tmp_path)
    assert summary["status"] == "pass"
    assert summary["metadata"]["target"] == "sip:echo@example.com"
    assert summary["extras"]["cleanup"] == "hangup_clean"


def test_call_soak_fails_when_call_never_reaches_connected_media(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The call soak should exit non-zero when the target call terminates before media connects."""

    clock = FakeClock()
    manager = FakeVoIPManager(clock)
    manager.schedule_registration(0.1, RegistrationState.OK)
    _patch_clock(monkeypatch, clock)
    monkeypatch.setattr(voip_cli, "_build_voip_manager_for_drill", lambda _config_dir: manager)

    def fake_make_call(sip_address: str, contact_name: str | None = None) -> bool:
        manager._set_call_state(CallState.OUTGOING_RINGING)
        manager.schedule_call_state(0.2, CallState.END)
        return True

    monkeypatch.setattr(manager, "make_call", fake_make_call)

    result = runner.invoke(
        pi_validate_app,
        [
            "voip",
            "--soak", "call",
            "--soak-target",
            "sip:echo@example.com",
            "--registration-timeout",
            "1",
            "--connect-timeout",
            "1",
            "--soak-seconds",
            "1",
            "--hangup-timeout",
            "0.5",
            "--artifacts-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    summary = _load_summary(tmp_path)
    assert summary["status"] == "fail"
    assert summary["reason"] == "Call never reached a connected state (last_state=end)"
    assert summary["extras"]["last_call_state"] == "end"


def test_call_soak_fails_fast_when_call_returns_to_idle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The connect wait should treat a rejected/unanswered call returning to IDLE as terminal."""

    clock = FakeClock()
    manager = FakeVoIPManager(clock)
    manager.schedule_registration(0.1, RegistrationState.OK)
    _patch_clock(monkeypatch, clock)
    monkeypatch.setattr(voip_cli, "_build_voip_manager_for_drill", lambda _config_dir: manager)

    def fake_make_call(sip_address: str, contact_name: str | None = None) -> bool:
        manager._set_call_state(CallState.OUTGOING_RINGING)
        manager.schedule_call_state(0.2, CallState.IDLE)
        return True

    monkeypatch.setattr(manager, "make_call", fake_make_call)

    result = runner.invoke(
        pi_validate_app,
        [
            "voip",
            "--soak", "call",
            "--soak-target",
            "sip:echo@example.com",
            "--registration-timeout",
            "1",
            "--connect-timeout",
            "5",
            "--soak-seconds",
            "1",
            "--hangup-timeout",
            "0.5",
            "--artifacts-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    summary = _load_summary(tmp_path)
    assert summary["status"] == "fail"
    assert summary["extras"]["last_call_state"] == "idle"
    assert summary["extras"]["connect_wait_seconds"] < 1.0


def test_call_soak_fails_when_manager_start_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The call soak should fail honestly when the VoIP manager cannot start."""

    clock = FakeClock()
    manager = FakeVoIPManager(clock)
    manager.start_result = False
    _patch_clock(monkeypatch, clock)
    monkeypatch.setattr(voip_cli, "_build_voip_manager_for_drill", lambda _config_dir: manager)

    result = runner.invoke(
        pi_validate_app,
        [
            "voip",
            "--soak", "call",
            "--soak-target",
            "sip:echo@example.com",
            "--artifacts-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    summary = _load_summary(tmp_path)
    assert summary["status"] == "fail"
    assert summary["reason"] == "VoIP manager failed to start"


def test_call_soak_fails_when_call_cannot_be_initiated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The call soak should fail honestly when make_call returns False."""

    clock = FakeClock()
    manager = FakeVoIPManager(clock)
    manager.schedule_registration(0.1, RegistrationState.OK)
    manager.make_call_result = False
    _patch_clock(monkeypatch, clock)
    monkeypatch.setattr(voip_cli, "_build_voip_manager_for_drill", lambda _config_dir: manager)

    result = runner.invoke(
        pi_validate_app,
        [
            "voip",
            "--soak", "call",
            "--soak-target",
            "sip:echo@example.com",
            "--registration-timeout",
            "1",
            "--artifacts-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    summary = _load_summary(tmp_path)
    assert summary["status"] == "fail"
    assert summary["reason"] == "Failed to initiate call to sip:echo@example.com"


def test_check_uses_custom_config_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The verbose registration check should honor the shared config-dir option."""

    clock = FakeClock()
    manager = FakeVoIPManager(clock)
    manager.schedule_registration(0.1, RegistrationState.OK)
    monkeypatch.setattr(voip_check_cli.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(voip_check_cli.time, "time", clock.time)
    monkeypatch.setattr(voip_check_cli.time, "sleep", clock.sleep)
    called_with: list[str] = []

    def fake_build(config_dir: str) -> FakeVoIPManager:
        called_with.append(config_dir)
        return manager

    monkeypatch.setattr(voip_check_cli, "_build_voip_manager", fake_build)

    result = runner.invoke(
        voip_check_cli.app,
        ["check", "--config-dir", "/tmp/custom-config"],
    )

    assert result.exit_code == 0
    assert called_with == ["/tmp/custom-config"]


def test_debug_uses_custom_config_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The incoming-call debug loop should honor the shared config-dir option."""

    clock = FakeClock()
    manager = FakeVoIPManager(clock)
    monkeypatch.setattr(voip_check_cli.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(voip_check_cli.time, "time", clock.time)
    monkeypatch.setattr(voip_check_cli.time, "sleep", clock.sleep)
    called_with: list[str] = []

    def fake_build(config_dir: str) -> FakeVoIPManager:
        called_with.append(config_dir)
        return manager

    def interrupting_iterate() -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(voip_check_cli, "_build_voip_manager", fake_build)
    monkeypatch.setattr(manager, "iterate", interrupting_iterate)

    result = runner.invoke(
        voip_check_cli.app,
        ["debug", "--config-dir", "/tmp/custom-config"],
    )

    assert result.exit_code == 0
    assert called_with == ["/tmp/custom-config"]
