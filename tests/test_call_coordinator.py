"""Focused tests for the call coordinator's config-driven status behavior."""

from __future__ import annotations

from pathlib import Path

from yoyopod.core import AppContext
from yoyopod.communication.calling.history import CallHistoryStore
from yoyopod.communication.models import CallState, RegistrationState
from yoyopod.coordinators.call import CallCoordinator
from yoyopod.coordinators.registry import CoordinatorRuntime
from yoyopod.core import CallFSM, CallInterruptionPolicy, MusicFSM


class _ScreenCoordinatorStub:
    """Small screen-coordinator double for call-coordinator tests."""

    def __init__(self, voip_manager: _VoipManagerStub | None = None) -> None:
        self.refresh_calls = 0
        self._voip_manager = voip_manager

    def refresh_call_screen_if_visible(self) -> None:
        self.refresh_calls += 1

    def show_incoming_call(self, caller_address: str, caller_name: str) -> None:
        return

    def show_outgoing_call(self, callee_address: str, callee_name: str) -> None:
        return

    def show_in_call(self) -> None:
        return

    def pop_call_screens(self) -> None:
        return

    def refresh_now_playing_screen(self) -> None:
        return

    def get_call_voip_manager(self) -> _VoipManagerStub | None:
        return self._voip_manager


class _ConfigManagerStub:
    """Small config-manager double exposing only the SIP accessors under test."""

    def __init__(self, *, sip_identity: str = "", sip_username: str = "") -> None:
        self._sip_identity = sip_identity
        self._sip_username = sip_username

    def get_sip_identity(self) -> str:
        return self._sip_identity

    def get_sip_username(self) -> str:
        return self._sip_username


class _VoipManagerStub:
    """Tiny VoIP manager surface used for call-history classification tests."""

    def __init__(self) -> None:
        self._caller_info = {
            "address": "sip:friend@example.com",
            "name": "Friend",
            "display_name": "Friend",
        }
        self._call_duration = 0
        self._pending_terminal_action: str | None = None

    def get_caller_info(self) -> dict[str, str]:
        return dict(self._caller_info)

    def get_call_duration(self) -> int:
        return self._call_duration

    def consume_pending_terminal_action(self) -> str | None:
        action = self._pending_terminal_action
        self._pending_terminal_action = None
        return action


def _build_runtime(
    *,
    config_manager: _ConfigManagerStub,
    context: AppContext,
) -> CoordinatorRuntime:
    """Create the minimal coordinator runtime required by CallCoordinator."""

    return CoordinatorRuntime(
        music_fsm=MusicFSM(),
        call_fsm=CallFSM(),
        call_interruption_policy=CallInterruptionPolicy(),
        screen_manager=None,
        music_backend=None,
        power_manager=None,
        config_manager=config_manager,
        context=context,
    )


def test_registration_change_uses_config_manager_for_voip_configured_status() -> None:
    """VoIP status should come from the canonical config manager, not legacy app config dicts."""

    context = AppContext()
    runtime = _build_runtime(
        config_manager=_ConfigManagerStub(sip_username="kid@example.com"),
        context=context,
    )
    screen_coordinator = _ScreenCoordinatorStub()
    coordinator = CallCoordinator(
        runtime=runtime,
        screen_coordinator=screen_coordinator,
        auto_resume_after_call=True,
    )

    coordinator.handle_registration_change(RegistrationState.OK)

    assert context.voip.configured is True
    assert context.voip.ready is True
    assert context.voip.running is True
    assert context.voip.registration_state == RegistrationState.OK.value
    assert runtime.voip_ready is True
    assert screen_coordinator.refresh_calls == 1


def test_availability_change_uses_reported_registration_state() -> None:
    """Availability changes should cache the registration state reported by the backend."""

    context = AppContext()
    runtime = _build_runtime(
        config_manager=_ConfigManagerStub(sip_username="kid@example.com"),
        context=context,
    )
    coordinator = CallCoordinator(
        runtime=runtime,
        screen_coordinator=_ScreenCoordinatorStub(),
        auto_resume_after_call=True,
    )

    coordinator.handle_availability_change(False, "backend_stopped", RegistrationState.NONE)

    assert context.voip.configured is True
    assert context.voip.ready is False
    assert context.voip.running is False
    assert context.voip.registration_state == RegistrationState.NONE.value


def test_terminal_call_states_record_rejected_and_failed_history(tmp_path: Path) -> None:
    """Terminal backend states should classify rejected and failed calls explicitly."""

    context = AppContext()
    voip_manager = _VoipManagerStub()
    runtime = _build_runtime(
        config_manager=_ConfigManagerStub(sip_username="kid@example.com"),
        context=context,
    )
    screen_coordinator = _ScreenCoordinatorStub(voip_manager=voip_manager)
    coordinator = CallCoordinator(
        runtime=runtime,
        screen_coordinator=screen_coordinator,
        auto_resume_after_call=True,
        call_history_store=CallHistoryStore(tmp_path / "call_history.json"),
    )

    coordinator.handle_incoming_call("sip:mama@example.com", "Mama")
    coordinator.handle_call_state_change(CallState.INCOMING)
    voip_manager._pending_terminal_action = "reject"
    coordinator.handle_call_state_change(CallState.END)

    voip_manager._caller_info = {
        "address": "sip:dad@example.com",
        "name": "Dad",
        "display_name": "Dad",
    }
    coordinator.handle_call_state_change(CallState.OUTGOING)
    coordinator.handle_call_state_change(CallState.ERROR)

    recent = coordinator.call_history_store.list_recent(2)  # type: ignore[union-attr]
    assert recent[0].outcome == "failed"
    assert recent[1].outcome == "rejected"
