"""Navigation soak flow helpers."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Callable

from loguru import logger

from yoyopod.core import UserActivityEvent
from yoyopod.ui.input import InputAction

from yoyopod.cli.pi.navigation.stats import NavigationSoakFailure

if TYPE_CHECKING:
    from yoyopod.app import YoyoPodApp
    from yoyopod.cli.pi.navigation.pump import _RuntimePump
    from yoyopod.cli.pi.navigation.runner import NavigationSoakRunner
    from yoyopod.ui.input import InputManager
    from yoyopod.ui.screens.manager import ScreenManager


class _NavigationExercises:
    """Own the action-driven flow logic for one navigation soak run."""

    _PLAYBACK_TIMEOUT_SECONDS = 8.0

    def __init__(self, runner: "NavigationSoakRunner") -> None:
        self._runner = runner

    @property
    def app(self) -> "YoyoPodApp":
        """Expose the active app for flow helpers."""

        return self._runner.app

    @property
    def pump(self) -> "_RuntimePump":
        """Expose the runtime pump for flow helpers."""

        return self._runner.pump

    def _screen_manager(self) -> "ScreenManager":
        """Return the active screen manager or fail fast."""

        screen_manager = self.app.screen_manager
        if screen_manager is None:
            raise NavigationSoakFailure("navigation soak screen manager is not initialized")
        return screen_manager

    def _input_manager(self) -> "InputManager":
        """Return the active input manager or fail fast."""

        input_manager = self.app.input_manager
        if input_manager is None:
            raise NavigationSoakFailure("navigation soak input manager is not initialized")
        return input_manager

    def current_screen_name(self) -> str:
        """Return the active route name."""

        current_screen = self._screen_manager().get_current_screen()
        route_name = None if current_screen is None else current_screen.route_name
        return route_name or "unknown"

    def require_screen(self, expected_screen: str) -> None:
        """Assert the active route name matches the expected screen."""

        actual_screen = self.current_screen_name()
        if actual_screen != expected_screen:
            raise NavigationSoakFailure(f"expected screen {expected_screen}, got {actual_screen}")

    def simulate_action(
        self,
        action: InputAction,
        *,
        expected_screen: str | None = None,
        label: str,
        settle_seconds: float | None = None,
    ) -> None:
        """Send one semantic action through the real input dispatcher."""

        logger.info(
            "Navigation soak action: {} on {}",
            label,
            self.current_screen_name(),
        )
        self._input_manager().simulate_action(action)
        self._runner.stats.actions += 1
        self.pump.run_for(self._runner.hold_seconds if settle_seconds is None else settle_seconds)

        if expected_screen is not None:
            actual_screen = self.current_screen_name()
            if actual_screen != expected_screen:
                raise NavigationSoakFailure(
                    f"{label} expected {expected_screen}, got {actual_screen}"
                )

    def idle_phase(self, label: str, duration_seconds: float) -> None:
        """Leave the app idle for one explicit dwell period."""

        if duration_seconds <= 0:
            return

        logger.info(
            "Navigation soak idle: {} for {:.1f}s on {}",
            label,
            duration_seconds,
            self.current_screen_name(),
        )
        self._runner.stats.explicit_idle_seconds += duration_seconds
        self.pump.run_for(duration_seconds)

    def _advance_until(
        self,
        *,
        expected_screen: str,
        target_value: str,
        current_value: Callable[[], str],
        label: str,
        max_steps: int,
    ) -> None:
        """Advance through one carousel or list until the requested item is selected."""

        for _ in range(max_steps):
            if current_value() == target_value:
                return
            self.simulate_action(
                InputAction.ADVANCE,
                expected_screen=expected_screen,
                label=label,
            )

        raise NavigationSoakFailure(f"could not reach {target_value} on {expected_screen}")

    def _hub_cards(self) -> list[object]:
        """Return the live hub cards using the most stable API available."""

        self.require_screen("hub")
        hub_screen = self._screen_manager().get_current_screen()
        card_factory = None if hub_screen is None else getattr(hub_screen, "cards", None)
        if callable(card_factory):
            cards = list(card_factory())
        else:
            private_card_factory = (
                None if hub_screen is None else getattr(hub_screen, "_cards", None)
            )
            cards = [] if not callable(private_card_factory) else list(private_card_factory())

        if not cards:
            raise NavigationSoakFailure("hub has no cards to navigate")
        return cards

    def _hub_mode(self) -> str:
        """Return the selected hub card mode."""

        hub_screen = self._screen_manager().get_current_screen()
        cards = self._hub_cards()
        selected_index = 0 if hub_screen is None else int(getattr(hub_screen, "selected_index", 0))
        mode = getattr(cards[selected_index % len(cards)], "mode", None)
        if mode is None:
            raise NavigationSoakFailure("hub card is missing mode metadata")
        return str(mode)

    def _listen_item_key(self) -> str:
        """Return the selected Listen landing item key."""

        self.require_screen("listen")
        listen_screen = self._screen_manager().get_current_screen()
        items = [] if listen_screen is None else getattr(listen_screen, "items", [])
        if not items:
            raise NavigationSoakFailure("listen screen has no items to navigate")
        selected_index = (
            0 if listen_screen is None else int(getattr(listen_screen, "selected_index", 0))
        )
        key = getattr(items[selected_index % len(items)], "key", None)
        if key is None:
            raise NavigationSoakFailure("listen item is missing key metadata")
        return str(key)

    def _move_hub_to(self, mode: str) -> None:
        """Advance the hub carousel until one mode is selected."""

        self._advance_until(
            expected_screen="hub",
            target_value=mode,
            current_value=self._hub_mode,
            label=f"hub advance to {mode}",
            max_steps=8,
        )

    def _move_listen_to(self, key: str) -> None:
        """Advance the Listen landing screen until one item is selected."""

        self._advance_until(
            expected_screen="listen",
            target_value=key,
            current_value=self._listen_item_key,
            label=f"listen advance to {key}",
            max_steps=8,
        )

    def _current_track_name(self) -> str | None:
        """Return the current track name when playback is active."""

        music_backend = self.app.music_backend
        if music_backend is None or not music_backend.is_connected:
            return None
        current_track = music_backend.get_current_track()
        if current_track is None:
            return None
        return current_track.name

    def _wait_for_playback_started(self, context_label: str) -> None:
        """Wait until playback produces one current track snapshot."""

        if not self._runner.with_playback:
            return

        deadline = time.monotonic() + self._PLAYBACK_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            current_track_name = self._current_track_name()
            if current_track_name is not None:
                self._runner.stats.playback_verified = True
                self._runner.stats.last_track_name = current_track_name
                return
            self.pump.run_for(0.2)

        raise NavigationSoakFailure(
            f"{context_label} did not produce a playable track within "
            f"{self._PLAYBACK_TIMEOUT_SECONDS:.1f}s"
        )

    def _wait_for_track_change(
        self,
        *,
        previous_track_name: str | None,
        context_label: str,
    ) -> None:
        """Wait until the current track changes after a skip action."""

        deadline = time.monotonic() + self._PLAYBACK_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            current_track_name = self._current_track_name()
            if current_track_name is not None and current_track_name != previous_track_name:
                self._runner.stats.last_track_name = current_track_name
                self._runner.stats.playback_verified = True
                return
            self.pump.run_for(0.2)

        raise NavigationSoakFailure(
            f"{context_label} did not change the current track within "
            f"{self._PLAYBACK_TIMEOUT_SECONDS:.1f}s"
        )

    def _exercise_now_playing(self, *, phase_label: str, back_target: str) -> None:
        """Exercise idle, play/pause, and next-track on Now Playing."""

        self.require_screen("now_playing")
        self._wait_for_playback_started(phase_label)
        self.idle_phase(f"{phase_label}_idle", self._runner.idle_seconds)

        self.simulate_action(
            InputAction.PLAY_PAUSE,
            expected_screen="now_playing",
            label=f"{phase_label} pause",
        )
        self.pump.run_for(self._runner.hold_seconds)
        self.simulate_action(
            InputAction.PLAY_PAUSE,
            expected_screen="now_playing",
            label=f"{phase_label} resume",
        )

        previous_track_name = self._current_track_name()
        self.simulate_action(
            InputAction.NEXT_TRACK,
            expected_screen="now_playing",
            label=f"{phase_label} next track",
        )
        self._wait_for_track_change(
            previous_track_name=previous_track_name,
            context_label=phase_label,
        )
        self.idle_phase(f"{phase_label}_post_next_idle", self._runner.idle_seconds)
        self.simulate_action(
            InputAction.BACK,
            expected_screen=back_target,
            label=f"{phase_label} back",
        )

    def _exercise_listen_branch(self) -> None:
        """Exercise Listen, playlists, recent, and playback-related navigation."""

        self._move_hub_to("listen")
        self.simulate_action(
            InputAction.SELECT,
            expected_screen="listen",
            label="open Listen",
        )
        self.idle_phase("listen_landing", self._runner.idle_seconds)

        self._move_listen_to("playlists")
        self.simulate_action(
            InputAction.SELECT,
            expected_screen="playlists",
            label="open Playlists",
        )
        self.idle_phase("playlists_idle", self._runner.idle_seconds)

        if self._runner.with_playback:
            playlist_screen = self._screen_manager().get_current_screen()
            playlists = [] if playlist_screen is None else getattr(playlist_screen, "playlists", [])
            if not playlists:
                raise NavigationSoakFailure(
                    "playlists screen is empty; disable playback or provision test music"
                )
            self.simulate_action(
                InputAction.SELECT,
                expected_screen="now_playing",
                label="load validation playlist",
            )
            self._exercise_now_playing(
                phase_label="playlist_playback",
                back_target="playlists",
            )

        self.simulate_action(
            InputAction.BACK,
            expected_screen="listen",
            label="back to Listen from Playlists",
        )

        self._move_listen_to("recent")
        self.simulate_action(
            InputAction.SELECT,
            expected_screen="recent_tracks",
            label="open Recent",
        )
        self.idle_phase("recent_tracks_idle", self._runner.idle_seconds)
        self.simulate_action(
            InputAction.BACK,
            expected_screen="listen",
            label="back to Listen from Recent",
        )

        if self._runner.with_playback:
            self._move_listen_to("shuffle")
            self.simulate_action(
                InputAction.SELECT,
                expected_screen="now_playing",
                label="shuffle local music",
            )
            self._exercise_now_playing(
                phase_label="shuffle_playback",
                back_target="listen",
            )

        self.simulate_action(
            InputAction.BACK,
            expected_screen="hub",
            label="back to Hub from Listen",
        )

    def _exercise_simple_hub_branch(
        self,
        *,
        mode: str,
        target_screen: str,
        idle_label: str,
    ) -> None:
        """Open one hub card, idle briefly, and return."""

        self._move_hub_to(mode)
        self.simulate_action(
            InputAction.SELECT,
            expected_screen=target_screen,
            label=f"open {mode}",
        )
        self.idle_phase(idle_label, self._runner.idle_seconds)
        self.simulate_action(
            InputAction.BACK,
            expected_screen="hub",
            label=f"back from {target_screen}",
        )

    def exercise_cycle(self) -> None:
        """Run one full navigation cycle."""

        self._exercise_listen_branch()
        self._exercise_simple_hub_branch(
            mode="talk",
            target_screen="call",
            idle_label="talk_idle",
        )
        self._exercise_simple_hub_branch(
            mode="ask",
            target_screen="ask",
            idle_label="ask_idle",
        )
        self._exercise_simple_hub_branch(
            mode="setup",
            target_screen="power",
            idle_label="power_idle",
        )
        self._move_hub_to("listen")

    def exercise_sleep_wake(self) -> None:
        """Force one sleep/wake cycle when screen timeout is enabled."""

        if self._runner.skip_sleep:
            self._runner.stats.sleep_wake_status = "skipped"
            return

        timeout_seconds = float(self.app._screen_timeout_seconds or 0.0)
        if timeout_seconds <= 0.0:
            self._runner.stats.sleep_wake_status = "timeout_disabled"
            return

        self.app._last_user_activity_at = time.monotonic() - timeout_seconds - 1.0
        self.pump.run_for(max(0.35, self._runner.hold_seconds))
        if self.app.context is None or self.app.context.screen.awake:
            raise NavigationSoakFailure("screen did not enter sleep during navigation soak")

        self.app.event_bus.publish(UserActivityEvent(action_name="navigation_soak"))
        self.pump.run_for(max(0.35, self._runner.hold_seconds))
        if self.app.context is None or not self.app.context.screen.awake:
            raise NavigationSoakFailure("screen did not wake after simulated navigation activity")

        self._runner.stats.sleep_wake_status = "ok"
