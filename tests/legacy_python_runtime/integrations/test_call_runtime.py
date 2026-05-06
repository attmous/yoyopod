"""Focused tests for the call runtime's config-driven status behavior."""

from __future__ import annotations

from yoyopod.core import AppContext
from yoyopod.core.app_state import AppStateRuntime
from yoyopod.integrations.call import (
    CallFSM,
    CallInterruptionPolicy,
)
from yoyopod.integrations.call.runtime import CallRuntime
from yoyopod.integrations.call.models import CallState, RegistrationState
from yoyopod.integrations.call.models import (
    VoIPCallSessionSnapshot,
    VoIPLifecycleSnapshot,
    VoIPRuntimeSnapshot,
)
from yoyopod.integrations.music import MusicFSM


class _ScreenManagerStub:
    """Small screen-manager double for call-runtime tests."""

    def __init__(self) -> None:
        self.refresh_calls = 0

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

    def owns_runtime_snapshot(self) -> bool:
        return True


def _build_runtime() -> AppStateRuntime:
    """Create the minimal derived runtime required by CallRuntime."""

    return AppStateRuntime(
        music_fsm=MusicFSM(),
        call_fsm=CallFSM(),
        call_interruption_policy=CallInterruptionPolicy(),
    )


def test_registration_change_uses_config_manager_for_voip_configured_status() -> None:
    """VoIP status should come from the canonical config manager, not legacy app config dicts."""

    context = AppContext()
    config_manager = _ConfigManagerStub(sip_username="kid@example.com")
    runtime = _build_runtime()
    screen_manager = _ScreenManagerStub()
    runtime_owner = CallRuntime(
        runtime=runtime,
        screen_manager=screen_manager,
        auto_resume_after_call=True,
        config_manager=config_manager,
        context=context,
        music_backend=None,
        voip_manager_provider=lambda: None,
    )

    runtime_owner.handle_registration_change(RegistrationState.OK)

    assert context.voip.configured is True
    assert context.voip.ready is True
    assert context.voip.running is True
    assert context.voip.registration_state == RegistrationState.OK.value
    assert runtime.voip_ready is True
    assert screen_manager.refresh_calls == 1


def test_availability_change_uses_reported_registration_state() -> None:
    """Availability changes should cache the registration state reported by the backend."""

    context = AppContext()
    config_manager = _ConfigManagerStub(sip_username="kid@example.com")
    runtime = _build_runtime()
    runtime_owner = CallRuntime(
        runtime=runtime,
        screen_manager=_ScreenManagerStub(),
        auto_resume_after_call=True,
        config_manager=config_manager,
        context=context,
        music_backend=None,
        voip_manager_provider=lambda: None,
    )

    runtime_owner.handle_availability_change(False, "backend_stopped", RegistrationState.NONE)

    assert context.voip.configured is True
    assert context.voip.ready is False
    assert context.voip.running is False
    assert context.voip.registration_state == RegistrationState.NONE.value


def test_call_runtime_is_snapshot_only_without_python_session_ownership() -> None:
    """Python call runtime should not expose direct call-state/session ownership hooks."""

    context = AppContext()
    voip_manager = _VoipManagerStub()
    config_manager = _ConfigManagerStub(sip_username="kid@example.com")
    runtime = _build_runtime()
    runtime_owner = CallRuntime(
        runtime=runtime,
        screen_manager=_ScreenManagerStub(),
        auto_resume_after_call=True,
        config_manager=config_manager,
        context=context,
        music_backend=None,
        voip_manager_provider=lambda: voip_manager,
    )

    assert not hasattr(runtime_owner, "handle_incoming_call")
    assert not hasattr(runtime_owner, "handle_call_state_change")
    assert not hasattr(runtime_owner, "call_history_store")
    assert not hasattr(runtime_owner, "_session_tracker")
    assert runtime.call_fsm.state.value == "idle"


def test_rust_snapshot_drives_call_runtime_without_python_history() -> None:
    """CallRuntime should consume Rust snapshots instead of finalizing Python history."""

    context = AppContext()
    voip_manager = _VoipManagerStub()
    runtime = _build_runtime()
    screen_manager = _ScreenManagerStub()
    runtime_owner = CallRuntime(
        runtime=runtime,
        screen_manager=screen_manager,
        auto_resume_after_call=True,
        config_manager=_ConfigManagerStub(sip_username="kid@example.com"),
        context=context,
        music_backend=None,
        voip_manager_provider=lambda: voip_manager,
    )

    runtime_owner.handle_runtime_snapshot_change(
        VoIPRuntimeSnapshot(
            configured=True,
            registered=True,
            registration_state=RegistrationState.OK,
            call_state=CallState.INCOMING,
            active_call_peer="sip:mama@example.com",
            lifecycle=VoIPLifecycleSnapshot(
                state="registered",
                reason="registered",
                backend_available=True,
            ),
            call_session=VoIPCallSessionSnapshot(
                active=True,
                session_id="call-1",
                direction="incoming",
                peer_sip_address="sip:mama@example.com",
            ),
        )
    )

    assert runtime.call_fsm.state.value == "incoming"

    runtime_owner.handle_runtime_snapshot_change(
        VoIPRuntimeSnapshot(
            configured=True,
            registered=True,
            registration_state=RegistrationState.OK,
            call_state=CallState.RELEASED,
            unseen_call_history=1,
            recent_call_history=(
                {
                    "session_id": "call-1",
                    "peer_sip_address": "sip:mama@example.com",
                    "direction": "incoming",
                    "outcome": "missed",
                    "duration_seconds": 0,
                    "seen": False,
                },
            ),
            lifecycle=VoIPLifecycleSnapshot(
                state="registered",
                reason="registered",
                backend_available=True,
            ),
            call_session=VoIPCallSessionSnapshot(
                active=False,
                session_id="call-1",
                direction="incoming",
                peer_sip_address="sip:mama@example.com",
                terminal_state=CallState.RELEASED.value,
                history_outcome="missed",
            ),
        )
    )

    assert runtime.call_fsm.state.value == "idle"
    assert context.talk.missed_calls == 1
    assert context.talk.recent_calls == ["mama"]
