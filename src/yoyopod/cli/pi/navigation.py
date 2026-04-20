"""Target-hardware navigation and idle soak helpers."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterator

from loguru import logger

from yoyopod.audio.test_music import (
    DEFAULT_TEST_MUSIC_TARGET_DIR,
    provision_test_music_library,
)
from yoyopod.events import UserActivityEvent
from yoyopod.ui.input import InputAction, InteractionProfile

if TYPE_CHECKING:
    from yoyopod.app import YoyoPodApp


class NavigationSoakFailure(RuntimeError):
    """Raised when the navigation soak cannot complete its expected path."""


@dataclass(slots=True)
class NavigationSoakStats:
    """Accumulate compact soak diagnostics for the final summary."""

    actions: int = 0
    visited_screens: set[str] = field(default_factory=set)
    explicit_idle_seconds: float = 0.0
    max_runtime_iteration_ms: float = 0.0
    max_runtime_loop_gap_ms: float = 0.0
    max_voip_schedule_delay_ms: float = 0.0
    heaviest_blocking_span_name: str | None = None
    heaviest_blocking_span_ms: float = 0.0
    last_track_name: str | None = None
    playback_verified: bool = False
    sleep_wake_status: str = "skipped"

    def observe_snapshot(self, snapshot: dict[str, float | int | None]) -> None:
        """Record high-level loop timing from one runtime snapshot."""

        runtime_iteration = snapshot.get("runtime_iteration_seconds")
        if runtime_iteration is not None:
            self.max_runtime_iteration_ms = max(
                self.max_runtime_iteration_ms,
                float(runtime_iteration) * 1000.0,
            )

        loop_gap = snapshot.get("runtime_loop_gap_seconds")
        if loop_gap is not None:
            self.max_runtime_loop_gap_ms = max(
                self.max_runtime_loop_gap_ms,
                float(loop_gap) * 1000.0,
            )

        voip_schedule_delay = snapshot.get("voip_schedule_delay_seconds")
        if voip_schedule_delay is not None:
            self.max_voip_schedule_delay_ms = max(
                self.max_voip_schedule_delay_ms,
                float(voip_schedule_delay) * 1000.0,
            )

        blocking_name = snapshot.get("runtime_blocking_span_name")
        blocking_seconds = snapshot.get("runtime_blocking_span_seconds")
        if blocking_name and blocking_seconds is not None:
            blocking_ms = float(blocking_seconds) * 1000.0
            if blocking_ms >= self.heaviest_blocking_span_ms:
                self.heaviest_blocking_span_ms = blocking_ms
                self.heaviest_blocking_span_name = str(blocking_name)


@contextmanager
def _temporary_env_var(name: str, value: str | None) -> Iterator[None]:
    """Temporarily override one environment variable."""

    previous = os.environ.get(name)
    if value is None:
        yield
        return

    os.environ[name] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


class _RuntimePump:
    """Drive the app loop without entering the long-running production loop."""

    def __init__(self, app: "YoyoPodApp", stats: NavigationSoakStats) -> None:
        self._app = app
        self._stats = stats
        self._last_screen_update = time.time()
        self._screen_update_interval = 1.0

    def run_for(self, duration_seconds: float) -> None:
        """Pump the app for the requested duration."""

        deadline = time.monotonic() + max(0.0, duration_seconds)
        while time.monotonic() < deadline:
            time.sleep(min(0.05, max(0.01, self._app._voip_iterate_interval_seconds)))
            monotonic_now = time.monotonic()
            current_time = time.time()
            iteration_started_at = time.monotonic()
            self._last_screen_update = self._app.runtime_loop.run_iteration(
                monotonic_now=monotonic_now,
                current_time=current_time,
                last_screen_update=self._last_screen_update,
                screen_update_interval=self._screen_update_interval,
            )
            iteration_duration_ms = (time.monotonic() - iteration_started_at) * 1000.0
            self._stats.max_runtime_iteration_ms = max(
                self._stats.max_runtime_iteration_ms,
                iteration_duration_ms,
            )

            current_screen = self._app.screen_manager.get_current_screen()
            if current_screen is not None and current_screen.route_name is not None:
                self._stats.visited_screens.add(current_screen.route_name)

            snapshot = self._app.runtime_loop.timing_snapshot(now=monotonic_now)
            self._stats.observe_snapshot(snapshot)

            if self._app._shutdown_completed:
                raise NavigationSoakFailure(
                    "app completed shutdown unexpectedly during navigation soak"
                )


class NavigationSoakRunner:
    """Exercise the target one-button UI with repeatable action-driven flows."""

    _PLAYBACK_TIMEOUT_SECONDS = 8.0

    def __init__(
        self,
        *,
        config_dir: str,
        cycles: int,
        hold_seconds: float,
        idle_seconds: float,
        tail_idle_seconds: float,
        with_playback: bool,
        provision_test_music: bool,
        test_music_dir: str,
        skip_sleep: bool,
    ) -> None:
        self.config_dir = config_dir
        self.cycles = max(1, cycles)
        self.hold_seconds = max(0.05, hold_seconds)
        self.idle_seconds = max(0.0, idle_seconds)
        self.tail_idle_seconds = max(0.0, tail_idle_seconds)
        self.with_playback = with_playback
        self.provision_test_music = provision_test_music
        self.test_music_dir = test_music_dir
        self.skip_sleep = skip_sleep

        self.stats = NavigationSoakStats()
        self._app: YoyoPodApp | None = None
        self._pump: _RuntimePump | None = None

    def run(self) -> tuple[bool, str]:
        """Run the full soak and return success plus one-line details."""

        from yoyopod.app import YoyoPodApp

        music_dir_override = None
        if self.with_playback and self.provision_test_music:
            library = provision_test_music_library(Path(self.test_music_dir))
            music_dir_override = str(library.target_dir)
            logger.info(
                "Navigation soak provisioned validation music at {}",
                music_dir_override,
            )

        with _temporary_env_var("YOYOPOD_MUSIC_DIR", music_dir_override):
            app = YoyoPodApp(config_dir=self.config_dir, simulate=False)
            self._app = app
            if not app.setup():
                try:
                    app.stop()
                except Exception:
                    logger.exception("Navigation soak cleanup failed after unsuccessful app setup")
                return False, "app setup failed"

            try:
                if app.display is None or app.screen_manager is None or app.input_manager is None:
                    return False, "display, screen manager, or input manager not initialized"
                if app.display.backend_kind != "lvgl":
                    return False, f"backend is {app.display.backend_kind}, expected lvgl"
                if app.input_manager.interaction_profile != InteractionProfile.ONE_BUTTON:
                    profile_name = app.input_manager.interaction_profile.value
                    return False, f"profile is {profile_name}, expected one_button"

                app.power_runtime.start_watchdog(now=time.monotonic())
                self._pump = _RuntimePump(app, self.stats)
                self._pump.run_for(self.hold_seconds)

                self._require_screen("hub")
                for cycle_number in range(1, self.cycles + 1):
                    logger.info(
                        "Navigation soak cycle {}/{}",
                        cycle_number,
                        self.cycles,
                    )
                    self._exercise_cycle()

                self._idle_phase("hub_tail_idle", self.tail_idle_seconds)
                self._exercise_sleep_wake()
            except NavigationSoakFailure as exc:
                return False, str(exc)
            finally:
                app.stop()

        return True, self._summary_details()

    @property
    def app(self) -> "YoyoPodApp":
        """Return the active app or raise when the runner is uninitialized."""

        if self._app is None:
            raise NavigationSoakFailure("navigation soak app is not initialized")
        return self._app

    @property
    def pump(self) -> _RuntimePump:
        """Return the runtime pump or raise when the runner is uninitialized."""

        if self._pump is None:
            raise NavigationSoakFailure("navigation soak runtime pump is not initialized")
        return self._pump

    def _summary_details(self) -> str:
        """Return a compact summary string for CLI output."""

        blocking_span = "none"
        if self.stats.heaviest_blocking_span_name is not None:
            blocking_span = (
                f"{self.stats.heaviest_blocking_span_name}:"
                f"{self.stats.heaviest_blocking_span_ms:.1f}ms"
            )

        screen_list = ",".join(sorted(self.stats.visited_screens)) or "none"
        playback_state = "verified" if self.stats.playback_verified else "not_requested"
        if self.with_playback and not self.stats.playback_verified:
            playback_state = "requested_not_verified"

        track_name = self.stats.last_track_name or "none"
        return (
            f"profile=one_button, cycles={self.cycles}, actions={self.stats.actions}, "
            f"screens={screen_list}, explicit_idle_s={self.stats.explicit_idle_seconds:.1f}, "
            f"playback={playback_state}, last_track={track_name}, "
            f"max_iteration_ms={self.stats.max_runtime_iteration_ms:.1f}, "
            f"max_loop_gap_ms={self.stats.max_runtime_loop_gap_ms:.1f}, "
            f"max_voip_delay_ms={self.stats.max_voip_schedule_delay_ms:.1f}, "
            f"heaviest_span={blocking_span}, sleep_wake={self.stats.sleep_wake_status}"
        )

    def _current_screen_name(self) -> str:
        """Return the active route name."""

        current_screen = self.app.screen_manager.get_current_screen()
        route_name = None if current_screen is None else current_screen.route_name
        return route_name or "unknown"

    def _require_screen(self, expected_screen: str) -> None:
        """Assert the active route name matches the expected screen."""

        actual_screen = self._current_screen_name()
        if actual_screen != expected_screen:
            raise NavigationSoakFailure(f"expected screen {expected_screen}, got {actual_screen}")

    def _simulate_action(
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
            self._current_screen_name(),
        )
        self.app.input_manager.simulate_action(action)
        self.stats.actions += 1
        self.pump.run_for(self.hold_seconds if settle_seconds is None else settle_seconds)

        if expected_screen is not None:
            actual_screen = self._current_screen_name()
            if actual_screen != expected_screen:
                raise NavigationSoakFailure(
                    f"{label} expected {expected_screen}, got {actual_screen}"
                )

    def _idle_phase(self, label: str, duration_seconds: float) -> None:
        """Leave the app idle for one explicit dwell period."""

        if duration_seconds <= 0:
            return

        logger.info(
            "Navigation soak idle: {} for {:.1f}s on {}",
            label,
            duration_seconds,
            self._current_screen_name(),
        )
        self.stats.explicit_idle_seconds += duration_seconds
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
            self._simulate_action(
                InputAction.ADVANCE,
                expected_screen=expected_screen,
                label=label,
            )

        raise NavigationSoakFailure(f"could not reach {target_value} on {expected_screen}")

    def _hub_mode(self) -> str:
        """Return the selected hub card mode."""

        self._require_screen("hub")
        hub_screen = self.app.screen_manager.get_current_screen()
        cards = [] if hub_screen is None else hub_screen._cards()
        if not cards:
            raise NavigationSoakFailure("hub has no cards to navigate")
        return cards[hub_screen.selected_index % len(cards)].mode

    def _listen_item_key(self) -> str:
        """Return the selected Listen landing item key."""

        self._require_screen("listen")
        listen_screen = self.app.screen_manager.get_current_screen()
        items = [] if listen_screen is None else getattr(listen_screen, "items", [])
        if not items:
            raise NavigationSoakFailure("listen screen has no items to navigate")
        return items[listen_screen.selected_index % len(items)].key

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

        if not self.with_playback:
            return

        deadline = time.monotonic() + self._PLAYBACK_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            current_track_name = self._current_track_name()
            if current_track_name is not None:
                self.stats.playback_verified = True
                self.stats.last_track_name = current_track_name
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
                self.stats.last_track_name = current_track_name
                self.stats.playback_verified = True
                return
            self.pump.run_for(0.2)

        raise NavigationSoakFailure(
            f"{context_label} did not change the current track within "
            f"{self._PLAYBACK_TIMEOUT_SECONDS:.1f}s"
        )

    def _exercise_now_playing(self, *, phase_label: str, back_target: str) -> None:
        """Exercise idle, play/pause, and next-track on Now Playing."""

        self._require_screen("now_playing")
        self._wait_for_playback_started(phase_label)
        self._idle_phase(f"{phase_label}_idle", self.idle_seconds)

        self._simulate_action(
            InputAction.PLAY_PAUSE,
            expected_screen="now_playing",
            label=f"{phase_label} pause",
        )
        self.pump.run_for(self.hold_seconds)
        self._simulate_action(
            InputAction.PLAY_PAUSE,
            expected_screen="now_playing",
            label=f"{phase_label} resume",
        )

        previous_track_name = self._current_track_name()
        self._simulate_action(
            InputAction.NEXT_TRACK,
            expected_screen="now_playing",
            label=f"{phase_label} next track",
        )
        self._wait_for_track_change(
            previous_track_name=previous_track_name,
            context_label=phase_label,
        )
        self._idle_phase(f"{phase_label}_post_next_idle", self.idle_seconds)
        self._simulate_action(
            InputAction.BACK,
            expected_screen=back_target,
            label=f"{phase_label} back",
        )

    def _exercise_listen_branch(self) -> None:
        """Exercise Listen, playlists, recent, and playback-related navigation."""

        self._move_hub_to("listen")
        self._simulate_action(
            InputAction.SELECT,
            expected_screen="listen",
            label="open Listen",
        )
        self._idle_phase("listen_landing", self.idle_seconds)

        self._move_listen_to("playlists")
        self._simulate_action(
            InputAction.SELECT,
            expected_screen="playlists",
            label="open Playlists",
        )
        self._idle_phase("playlists_idle", self.idle_seconds)

        if self.with_playback:
            playlist_screen = self.app.screen_manager.get_current_screen()
            playlists = [] if playlist_screen is None else getattr(playlist_screen, "playlists", [])
            if not playlists:
                raise NavigationSoakFailure(
                    "playlists screen is empty; disable playback or provision test music"
                )
            self._simulate_action(
                InputAction.SELECT,
                expected_screen="now_playing",
                label="load validation playlist",
            )
            self._exercise_now_playing(
                phase_label="playlist_playback",
                back_target="playlists",
            )

        self._simulate_action(
            InputAction.BACK,
            expected_screen="listen",
            label="back to Listen from Playlists",
        )

        self._move_listen_to("recent")
        self._simulate_action(
            InputAction.SELECT,
            expected_screen="recent_tracks",
            label="open Recent",
        )
        self._idle_phase("recent_tracks_idle", self.idle_seconds)
        self._simulate_action(
            InputAction.BACK,
            expected_screen="listen",
            label="back to Listen from Recent",
        )

        if self.with_playback:
            self._move_listen_to("shuffle")
            self._simulate_action(
                InputAction.SELECT,
                expected_screen="now_playing",
                label="shuffle local music",
            )
            self._exercise_now_playing(
                phase_label="shuffle_playback",
                back_target="listen",
            )

        self._simulate_action(
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
        self._simulate_action(
            InputAction.SELECT,
            expected_screen=target_screen,
            label=f"open {mode}",
        )
        self._idle_phase(idle_label, self.idle_seconds)
        self._simulate_action(
            InputAction.BACK,
            expected_screen="hub",
            label=f"back from {target_screen}",
        )

    def _exercise_cycle(self) -> None:
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

    def _exercise_sleep_wake(self) -> None:
        """Force one sleep/wake cycle when screen timeout is enabled."""

        if self.skip_sleep:
            self.stats.sleep_wake_status = "skipped"
            return

        timeout_seconds = float(self.app._screen_timeout_seconds or 0.0)
        if timeout_seconds <= 0.0:
            self.stats.sleep_wake_status = "timeout_disabled"
            return

        self.app._last_user_activity_at = time.monotonic() - timeout_seconds - 1.0
        self.pump.run_for(max(0.35, self.hold_seconds))
        if self.app.context is None or self.app.context.screen.awake:
            raise NavigationSoakFailure("screen did not enter sleep during navigation soak")

        self.app.event_bus.publish(UserActivityEvent(action_name="navigation_soak"))
        self.pump.run_for(max(0.35, self.hold_seconds))
        if self.app.context is None or not self.app.context.screen.awake:
            raise NavigationSoakFailure("screen did not wake after simulated navigation activity")

        self.stats.sleep_wake_status = "ok"


def run_navigation_soak(
    *,
    config_dir: str = "config",
    cycles: int = 2,
    hold_seconds: float = 0.35,
    idle_seconds: float = 3.0,
    tail_idle_seconds: float = 10.0,
    with_playback: bool = True,
    provision_test_music: bool = True,
    test_music_dir: str = DEFAULT_TEST_MUSIC_TARGET_DIR,
    skip_sleep: bool = False,
) -> tuple[bool, str]:
    """Run the target-hardware navigation and idle stability soak."""

    runner = NavigationSoakRunner(
        config_dir=config_dir,
        cycles=cycles,
        hold_seconds=hold_seconds,
        idle_seconds=idle_seconds,
        tail_idle_seconds=tail_idle_seconds,
        with_playback=with_playback,
        provision_test_music=provision_test_music,
        test_music_dir=test_music_dir,
        skip_sleep=skip_sleep,
    )
    return runner.run()
