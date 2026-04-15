"""Thin Ask screen hooks over the shared runtime-owned voice coordinator."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from yoyopy.runtime.voice import VoiceCommandOutcome, VoiceRuntimeCoordinator

if TYPE_CHECKING:
    from yoyopy.runtime_state import VoiceInteractionState
    from yoyopy.voice import VoiceService, VoiceSettings


class AskScreenVoiceMixin:
    """Keep Ask focused on interaction hooks while runtime owns orchestration."""

    voice_runtime: VoiceRuntimeCoordinator

    def on_select(self, data=None) -> None:
        """Start listening, or ask again from the reply state."""

        self.voice_runtime.begin_listening(async_capture=self._async_voice_capture)

    def on_back(self, data=None) -> None:
        """Cancel any in-flight capture and pop the screen."""

        self.voice_runtime.cancel()
        self._cancel_auto_return()
        self.request_route("back")

    def on_voice_command(self, data=None) -> None:
        """Execute a supplied transcript through the shared runtime seam."""

        transcript = self._extract_transcript(data)
        self.voice_runtime.handle_transcript(transcript)

    def on_ptt_release(self, data=None) -> None:
        """Stop PTT recording when the button is released after a hold."""

        self.voice_runtime.finish_ptt_capture()

    def _bind_voice_runtime(self) -> None:
        """Bind screen-local consumers to the shared voice runtime."""

        dispatcher = None
        if self.screen_manager is not None:
            dispatcher = getattr(self.screen_manager, "action_scheduler", None)
        self.voice_runtime.bind(
            state_listener=self._on_voice_runtime_state_changed,
            outcome_listener=self._on_voice_runtime_outcome,
            dispatcher=dispatcher,
        )
        self._on_voice_runtime_state_changed(self.voice_runtime.state)

    def _on_voice_runtime_state_changed(self, state: "VoiceInteractionState") -> None:
        """Mirror shared voice runtime state into Ask presentation fields."""

        self._state = state.phase
        self._headline = state.headline
        self._body = state.body
        self._capture_in_flight = state.capture_in_flight
        self._ptt_active = state.ptt_active
        self._listen_generation = state.generation
        self._refresh_after_state_change()

    def _on_voice_runtime_outcome(self, outcome: VoiceCommandOutcome) -> None:
        """Handle navigation side effects emitted by the shared voice runtime."""

        navigated = False
        if outcome.route_name is not None:
            self.request_route(outcome.route_name)
            navigated = self._apply_pending_navigation_request()
        if not navigated:
            self._schedule_auto_return()

    def _voice_service(self) -> "VoiceService":
        """Compatibility shim for tests that inspect the effective service."""

        return self.voice_runtime._voice_service()

    def _voice_settings(self) -> "VoiceSettings":
        """Compatibility shim for tests that inspect the resolved settings."""

        return self.voice_runtime.settings()

    def _default_voice_settings(self) -> "VoiceSettings":
        """Compatibility shim for tests that inspect config-derived defaults."""

        return self.voice_runtime.defaults()

    def _dispatch_listen_result(
        self,
        transcript: str,
        *,
        capture_failed: bool,
        generation: int,
    ) -> None:
        """Compatibility shim around the shared listen-result dispatcher."""

        self.voice_runtime.state.generation = self._listen_generation
        self.voice_runtime.dispatch_listen_result(
            transcript,
            capture_failed=capture_failed,
            generation=generation,
        )

    def _run_ptt_listening_cycle(
        self,
        voice_service: "VoiceService",
        generation: int,
        cancel_event,
    ) -> None:
        """Compatibility shim used by existing tests."""

        self.voice_runtime.state.generation = self._listen_generation
        self.voice_runtime.state.ptt_active = self._ptt_active
        self.voice_runtime.state.capture_in_flight = self._capture_in_flight
        self.voice_runtime._run_ptt_listening_cycle(voice_service, generation, cancel_event)

    def _extract_transcript(self, data: object) -> str:
        """Return the transcript text from a voice-command event payload."""

        if isinstance(data, str):
            return data.strip()
        if isinstance(data, dict):
            value = data.get("command") or data.get("transcript") or data.get("text")
            if isinstance(value, str):
                return value.strip()
        return ""

    def _schedule_auto_return(self) -> None:
        """Pop back after 2 seconds in quick-command mode."""

        if not self._quick_command:
            return
        self._cancel_auto_return()
        self._auto_return_timer = threading.Timer(2.0, self._auto_pop)
        self._auto_return_timer.daemon = True
        self._auto_return_timer.start()

    def _auto_pop(self) -> None:
        """Return to the previous screen via the action scheduler."""

        self._auto_return_timer = None

        def apply_pop() -> None:
            self.request_route("back")
            self._apply_pending_navigation_request()

        scheduler = (
            getattr(self.screen_manager, "action_scheduler", None)
            if self.screen_manager is not None
            else None
        )
        if scheduler is not None:
            scheduler(apply_pop)
        else:
            apply_pop()

    def _cancel_auto_return(self) -> None:
        """Cancel any pending auto-return timer."""

        if self._auto_return_timer is not None:
            self._auto_return_timer.cancel()
            self._auto_return_timer = None

    def _apply_pending_navigation_request(self) -> bool:
        """Apply any queued navigation immediately when Ask triggers it off-input-path."""

        if self.screen_manager is None:
            return False
        navigation_request = self.consume_navigation_request()
        if navigation_request is None:
            return False
        return self.screen_manager.apply_navigation_request(
            navigation_request,
            source_screen=self,
        )
