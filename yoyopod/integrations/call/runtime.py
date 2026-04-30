"""Live call-runtime orchestration for YoYoPod."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger

from yoyopod.core.app_state import AppRuntimeState, AppStateRuntime
from yoyopod.integrations.call import (
    CallHistoryStore,
    CallRinger,
    CallSessionState,
    CallSessionTracker,
    CallState,
    RegistrationState,
    sync_context_voip_status,
)
from yoyopod.integrations.call.models import VoIPRuntimeSnapshot
from yoyopod.ui.screens.manager import ScreenManager

if TYPE_CHECKING:
    from yoyopod.backends.music import MusicBackend
    from yoyopod.config import ConfigManager
    from yoyopod.core import AppContext

_OUTGOING_STATES = {
    CallState.OUTGOING,
    CallState.OUTGOING_PROGRESS,
    CallState.OUTGOING_RINGING,
    CallState.OUTGOING_EARLY_MEDIA,
}
_ACTIVE_STATES = {
    CallState.CONNECTED,
    CallState.STREAMS_RUNNING,
    CallState.PAUSED,
    CallState.PAUSED_BY_REMOTE,
    CallState.UPDATED_BY_REMOTE,
}
_TERMINAL_STATES = {
    CallState.IDLE,
    CallState.RELEASED,
    CallState.END,
    CallState.ERROR,
}


class CallRuntime:
    """Own main-thread call orchestration for the live runtime."""

    def __init__(
        self,
        runtime: AppStateRuntime,
        screen_manager: ScreenManager | None,
        auto_resume_after_call: bool,
        config_manager: "ConfigManager | None",
        context: "AppContext | None",
        music_backend: "MusicBackend | None",
        voip_manager_provider: Callable[[], object | None],
        call_history_store: CallHistoryStore | None = None,
        initial_voip_registered: bool = False,
    ) -> None:
        self.runtime = runtime
        self.screen_manager = screen_manager
        self.auto_resume_after_call = auto_resume_after_call
        self.config_manager = config_manager
        self.context = context
        self.music_backend = music_backend
        self.voip_manager_provider = voip_manager_provider
        self.call_history_store = call_history_store
        self.voip_registered = initial_voip_registered
        self._ringer = CallRinger()
        self._session_tracker = CallSessionTracker(call_history_store)

    def start_ringing(self) -> None:
        """Start playing the ring tone for an incoming call."""
        self._ringer.start(self.config_manager)

    def stop_ringing(self) -> None:
        """Stop playing the ring tone."""
        self._ringer.stop()

    def cleanup(self) -> None:
        """Clean up call-related coordinator state."""
        self.stop_ringing()

    def on_enter_call_active_music_paused(self) -> None:
        """Log entry into the active-call-with-paused-music state."""
        logger.info("In call (music paused in background)")

    def handle_incoming_call(self, caller_address: str, caller_name: str) -> None:
        """Capture incoming-call metadata for the active incoming phase."""
        if self._current_manager_owns_runtime_snapshot():
            logger.debug("Waiting for Rust snapshot before mirroring incoming-call metadata")
            return
        logger.info(f"Incoming call metadata: {caller_name} ({caller_address})")
        self._session_tracker.begin_incoming_call(caller_address, caller_name)
        self._present_incoming_call_if_ready()

    def handle_call_state_change(self, state: CallState) -> None:
        """Coordinate high-level call state updates."""
        if self._current_manager_owns_runtime_snapshot():
            logger.debug("Waiting for Rust snapshot before mirroring call state {}", state.value)
            return

        logger.info(f"Call state changed: {state.value}")

        if state in (
            CallState.OUTGOING,
            CallState.OUTGOING_PROGRESS,
            CallState.OUTGOING_RINGING,
            CallState.OUTGOING_EARLY_MEDIA,
        ):
            self._pause_music_for_call(phase="outgoing")
            session = self._session_tracker.ensure_outgoing_call(self._current_caller_info())
            self.runtime.call_fsm.transition("dial")
            self.runtime.sync_app_state("call_outgoing")
            self._show_outgoing_call(
                session.sip_address,
                session.display_name,
            )
            return

        if state == CallState.INCOMING:
            self._pause_music_for_call(phase="incoming")
            self.runtime.call_fsm.transition("incoming")
            self.runtime.sync_app_state("call_incoming_state")
            self._present_incoming_call_if_ready()
            return

        if state in (CallState.CONNECTED, CallState.STREAMS_RUNNING):
            self._session_tracker.mark_answered()
            self.runtime.call_fsm.transition("connect")
            state_change = self.runtime.sync_app_state("call_connected")
            if state_change.entered(AppRuntimeState.CALL_ACTIVE_MUSIC_PAUSED):
                logger.info("In call (music paused in background)")
            self._show_in_call()
            self.stop_ringing()
            return

        if state in (CallState.RELEASED, CallState.END, CallState.ERROR):
            if not self._has_live_call_state():
                logger.debug("Ignoring duplicate terminal call state {}", state.value)
                return

            local_end_action = self._consume_pending_terminal_action()
            self._session_tracker.mark_terminal_state(
                state,
                local_end_action=local_end_action,
            )
            self.handle_call_ended(reason=state.value)
            return

        logger.debug("Call state {} does not change coordinator phase", state.value)

    def handle_call_ended(self, *, reason: str = "released") -> None:
        """Coordinate call cleanup and possible music resume."""
        if not self.runtime.call_fsm.is_active and not self._session_tracker.has_live_session:
            logger.warning(
                "Ignoring terminal call teardown without an active session (reason: {})",
                reason,
            )
            self.stop_ringing()
            self._session_tracker.clear_pending_incoming_call()
            self._pop_call_screens()
            self.runtime.sync_app_state(f"call_ended:{reason}")
            return

        logger.info("Call ended ({})", reason)

        self.stop_ringing()
        self._session_tracker.clear_pending_incoming_call()
        self._finalize_call_history()
        self._pop_call_screens()

        should_resume = self.runtime.call_interruption_policy.should_auto_resume(
            self.auto_resume_after_call
        )
        if self.runtime.call_fsm.is_active:
            self.runtime.call_fsm.transition("end")
        else:
            self.runtime.call_fsm.sync(CallSessionState.IDLE)

        if should_resume:
            if self._resume_music_after_call():
                logger.info("Auto-resumed music after call")
            else:
                logger.warning("Music remains paused after failed auto-resume")
                self.runtime.music_fsm.transition("pause")
        elif self.runtime.call_interruption_policy.music_interrupted_by_call:
            logger.info("Music stays paused (auto-resume disabled)")
            self.runtime.music_fsm.transition("pause")
        else:
            logger.info("No music to resume")

        self.runtime.call_interruption_policy.clear()
        self.runtime.sync_app_state("call_ended")

    def handle_registration_change(self, state: RegistrationState) -> None:
        """Coordinate registration updates and VoIP availability state."""
        logger.info(f"VoIP registration: {state.value}")

        self.voip_registered = state == RegistrationState.OK
        self.runtime.set_voip_ready(self.voip_registered)
        sync_context_voip_status(
            self.context,
            config_manager=self.config_manager,
            ready=self.voip_registered,
            running=True,
            registration_state=state,
        )

        if state == RegistrationState.OK:
            logger.info("VoIP ready to receive calls")
        elif state == RegistrationState.FAILED:
            logger.warning("VoIP registration failed")

        self._refresh_call_screen_if_visible()

    def handle_availability_change(
        self,
        available: bool,
        reason: str,
        registration_state: RegistrationState = RegistrationState.NONE,
    ) -> None:
        """Coordinate backend availability changes and forced call cleanup."""
        self.voip_registered = registration_state == RegistrationState.OK
        self.runtime.set_voip_ready(self.voip_registered)

        if available:
            logger.info(f"VoIP backend available ({reason or 'ready'})")
            sync_context_voip_status(
                self.context,
                config_manager=self.config_manager,
                ready=self.voip_registered,
                running=True,
                registration_state=registration_state,
            )
            self._refresh_call_screen_if_visible()
            return

        logger.warning(f"VoIP backend unavailable ({reason or 'unknown'})")
        sync_context_voip_status(
            self.context,
            config_manager=self.config_manager,
            ready=False,
            running=False,
            registration_state=registration_state,
        )
        self.stop_ringing()
        self._refresh_call_screen_if_visible()

        if self.runtime.call_fsm.is_active or self._session_tracker.has_live_session:
            if self._current_manager_owns_runtime_snapshot():
                self._end_rust_snapshot_call(reason=reason or "unavailable")
            else:
                self.handle_call_ended(reason=reason or "unavailable")

    def handle_runtime_snapshot_change(self, snapshot: VoIPRuntimeSnapshot) -> None:
        """Coordinate app side effects from the Rust-owned canonical VoIP snapshot."""

        logger.info("VoIP runtime snapshot call state: {}", snapshot.call_state.value)
        self._publish_call_summary_from_snapshot(snapshot)

        state = snapshot.call_state
        if state in _OUTGOING_STATES:
            self._pause_music_for_call(phase="outgoing")
            self.runtime.call_fsm.sync(CallSessionState.OUTGOING)
            self.runtime.sync_app_state("rust_call_outgoing")
            peer_address = snapshot.active_call_peer
            self._show_outgoing_call(peer_address, self._snapshot_peer_name(snapshot))
            self.stop_ringing()
            return

        if state == CallState.INCOMING:
            self._pause_music_for_call(phase="incoming")
            self.runtime.call_fsm.sync(CallSessionState.INCOMING)
            self.runtime.sync_app_state("rust_call_incoming")
            self._show_incoming_call(snapshot.active_call_peer, self._snapshot_peer_name(snapshot))
            self.start_ringing()
            return

        if state in _ACTIVE_STATES:
            self.runtime.call_fsm.sync(CallSessionState.ACTIVE)
            state_change = self.runtime.sync_app_state("rust_call_active")
            if state_change.entered(AppRuntimeState.CALL_ACTIVE_MUSIC_PAUSED):
                logger.info("In call (music paused in background)")
            self._show_in_call()
            self.stop_ringing()
            return

        if state in _TERMINAL_STATES:
            if (
                self.runtime.call_fsm.is_active
                or self.runtime.call_interruption_policy.music_interrupted_by_call
            ):
                self._end_rust_snapshot_call(reason=state.value)
            return

    def _pause_music_for_call(self, *, phase: str) -> None:
        """Pause active playback once when a call enters an interruption phase."""

        if self.runtime.call_interruption_policy.music_interrupted_by_call:
            return

        if self.music_backend is None or not self.music_backend.is_connected:
            logger.debug("Skipping auto-pause for {} call: music backend unavailable", phase)
            return

        if self.music_backend.get_playback_state() != "playing":
            return

        logger.info("Auto-pausing music for {} call", phase)
        if not self.music_backend.pause():
            logger.warning("Failed to auto-pause music for {} call", phase)
            return

        self.runtime.call_interruption_policy.mark_paused_for_call(self.runtime.music_fsm)

    def _resume_music_after_call(self) -> bool:
        """Resume interrupted music only when the backend confirms the command."""

        if self.music_backend is None or not self.music_backend.is_connected:
            logger.warning("Cannot auto-resume music after call: music backend unavailable")
            return False

        if not self.music_backend.play():
            return False

        self.runtime.music_fsm.transition("play")
        self._refresh_now_playing_screen()
        return True

    def _present_incoming_call_if_ready(self) -> None:
        """Show the incoming-call screen once state and caller metadata are both known."""

        if self.runtime.call_fsm.state != CallSessionState.INCOMING:
            return
        if self._session_tracker.pending_incoming_call is None:
            logger.debug("Incoming call phase entered before caller metadata arrived")
            return

        caller_address, caller_name = self._session_tracker.pending_incoming_call
        self._show_incoming_call(caller_address, caller_name)
        self.start_ringing()

    def _pop_call_screens(self) -> None:
        if self.screen_manager is None:
            return
        self.screen_manager.pop_call_screens()

    def _refresh_now_playing_screen(self) -> None:
        if self.screen_manager is None:
            return
        self.screen_manager.refresh_now_playing_screen()

    def _refresh_call_screen_if_visible(self) -> None:
        if self.screen_manager is None:
            return
        self.screen_manager.refresh_call_screen_if_visible()

    def _show_incoming_call(self, caller_address: str, caller_name: str) -> None:
        if self.screen_manager is None:
            return
        self.screen_manager.show_incoming_call(caller_address, caller_name)

    def _show_in_call(self) -> None:
        if self.screen_manager is None:
            return
        self.screen_manager.show_in_call()

    def _show_outgoing_call(self, callee_address: str, callee_name: str) -> None:
        if self.screen_manager is None:
            return
        self.screen_manager.show_outgoing_call(callee_address, callee_name)

    def _has_live_call_state(self) -> bool:
        """Return whether the coordinator still has a live call to tear down."""

        return self.runtime.call_fsm.is_active or self._session_tracker.has_live_session

    def _consume_pending_terminal_action(self) -> str | None:
        """Return any locally initiated teardown action awaiting terminal backend state."""

        voip_manager = self._current_voip_manager()
        consume_action = getattr(voip_manager, "consume_pending_terminal_action", None)
        if callable(consume_action):
            return consume_action()
        return None

    def _finalize_call_history(self) -> None:
        """Persist the just-finished call into the Talk history store."""

        self._session_tracker.finalize(
            call_duration_seconds=self._current_call_duration_seconds(),
        )
        self._publish_call_summary_to_context()

    def _publish_call_summary_to_context(self) -> None:
        """Refresh Talk summary data stored in the shared app context."""

        if self.context is None or self.call_history_store is None:
            return

        self.context.update_call_summary(
            missed_calls=self.call_history_store.missed_count(),
            recent_calls=self.call_history_store.recent_preview(),
        )

    def _publish_call_summary_from_snapshot(self, snapshot: VoIPRuntimeSnapshot) -> None:
        """Refresh Talk summary data from the Rust-owned call-history snapshot."""

        if self.context is None:
            return
        self.context.update_call_summary(
            missed_calls=max(0, int(snapshot.unseen_call_history)),
            recent_calls=_snapshot_recent_call_preview(snapshot),
        )

    def _current_voip_manager(self) -> object | None:
        """Return the live VoIP manager currently owned by the application."""

        return self.voip_manager_provider()

    def _current_manager_owns_runtime_snapshot(self) -> bool:
        manager = self._current_voip_manager()
        owns_runtime_snapshot = getattr(manager, "owns_runtime_snapshot", None)
        if not callable(owns_runtime_snapshot):
            return False
        return bool(owns_runtime_snapshot())

    def _end_rust_snapshot_call(self, *, reason: str) -> None:
        """Clean up a Rust-owned terminal call without writing Python history."""

        logger.info("Rust-owned call ended ({})", reason)
        self.stop_ringing()
        self._pop_call_screens()

        should_resume = self.runtime.call_interruption_policy.should_auto_resume(
            self.auto_resume_after_call
        )
        if self.runtime.call_fsm.is_active:
            self.runtime.call_fsm.transition("end")
        else:
            self.runtime.call_fsm.sync(CallSessionState.IDLE)

        if should_resume:
            if self._resume_music_after_call():
                logger.info("Auto-resumed music after call")
            else:
                logger.warning("Music remains paused after failed auto-resume")
                self.runtime.music_fsm.transition("pause")
        elif self.runtime.call_interruption_policy.music_interrupted_by_call:
            logger.info("Music stays paused (auto-resume disabled)")
            self.runtime.music_fsm.transition("pause")
        else:
            logger.info("No music to resume")

        self.runtime.call_interruption_policy.clear()
        self.runtime.sync_app_state(f"rust_call_ended:{reason}")

    def _snapshot_peer_name(self, snapshot: VoIPRuntimeSnapshot) -> str:
        caller = self._current_caller_info()
        display_name = str(caller.get("display_name") or caller.get("name") or "").strip()
        if display_name:
            return display_name
        return _extract_username(snapshot.active_call_peer)

    def _current_caller_info(self) -> dict[str, str]:
        """Return the current caller/callee metadata from the shared VoIP manager."""

        voip_manager = self._current_voip_manager()
        if voip_manager is None:
            return {}
        return dict(voip_manager.get_caller_info())

    def _current_call_duration_seconds(self) -> int:
        """Return the current call duration reported by the shared VoIP manager."""

        voip_manager = self._current_voip_manager()
        if voip_manager is None:
            return 0
        return int(voip_manager.get_call_duration())


def _snapshot_recent_call_preview(snapshot: VoIPRuntimeSnapshot) -> list[str]:
    preview: list[str] = []
    for raw_entry in snapshot.recent_call_history:
        if not isinstance(raw_entry, dict):
            continue
        peer_sip_address = str(raw_entry.get("peer_sip_address", "") or "").strip()
        if peer_sip_address:
            preview.append(_extract_username(peer_sip_address))
    return preview


def _extract_username(sip_address: str | None) -> str:
    if not sip_address:
        return "Unknown"
    if "@" in sip_address:
        username_part = sip_address.split("@", 1)[0]
        if ":" in username_part:
            return username_part.split(":")[-1]
        return username_part
    return sip_address
