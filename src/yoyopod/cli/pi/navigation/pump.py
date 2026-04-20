"""Navigation soak runtime loop pump."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from yoyopod.cli.pi.navigation.stats import NavigationSoakFailure, NavigationSoakStats

if TYPE_CHECKING:
    from yoyopod.app import YoyoPodApp


class _RuntimePump:
    """Drive the app loop without entering the long-running production loop."""

    def __init__(self, app: "YoyoPodApp", stats: "NavigationSoakStats") -> None:
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
