"""Navigation soak app handle protocol and adapters."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol

from .plan import NavigationSoakError


class _NavigationSoakAppHandle(Protocol):
    """Minimal runtime surface used by soak helpers."""

    @property
    def config_dir(self) -> str:
        """Return the config directory used for the soak app."""

    @property
    def simulate(self) -> bool:
        """Return whether the soak app is running in simulation mode."""

    @property
    def display(self) -> Any:
        """Return the active display facade."""

    @property
    def screen_manager(self) -> Any:
        """Return the active screen manager."""

    @property
    def input_manager(self) -> Any:
        """Return the active input manager."""

    @property
    def local_music_service(self) -> Any:
        """Return the local music service used by the soak."""

    @property
    def music_backend(self) -> Any:
        """Return the music backend used by the soak."""

    @property
    def runtime_loop(self) -> Any:
        """Return the runtime loop service."""

    @property
    def worker_supervisor(self) -> Any:
        """Return the managed worker supervisor."""

    @property
    def recovery_service(self) -> Any:
        """Return the recovery service."""

    @property
    def power_runtime(self) -> Any:
        """Return the power runtime facade."""

    @property
    def screen_power_service(self) -> Any:
        """Return the screen power service."""

    @property
    def scheduler(self) -> Any:
        """Return the main-thread scheduler used by the soak app."""

    @property
    def bus(self) -> Any:
        """Return the typed event bus."""

    @property
    def event_bus(self) -> Any:
        """Return the typed event bus."""

    @property
    def context(self) -> Any:
        """Return the shared runtime context."""

    def setup(self) -> bool:
        """Initialize app resources."""

    def stop(self) -> None:
        """Shut down app resources."""

    @property
    def voip_iterate_interval_seconds(self) -> float:
        """Return the configured runtime-loop VoIP iterate cadence."""

    @property
    def screen_timeout_seconds(self) -> float:
        """Return the configured inactivity timeout used for screen sleep."""

    @property
    def shutdown_completed(self) -> bool:
        """Return whether the app completed shutdown during the soak."""

    def simulate_inactivity(self, *, idle_for_seconds: float) -> None:
        """Pretend the app has been idle long enough to trigger sleep."""


@dataclass(slots=True)
class _YoyoPodAppNavigationSoakHandle:
    """Adapter that exposes a stable soak surface for ``YoyoPodApp``."""

    _app: Any

    @property
    def config_dir(self) -> str:
        return str(self._app.config_dir)

    @property
    def simulate(self) -> bool:
        return bool(self._app.simulate)

    @property
    def display(self) -> Any:
        return self._app.display

    @property
    def screen_manager(self) -> Any:
        return self._app.screen_manager

    @property
    def input_manager(self) -> Any:
        return self._app.input_manager

    @property
    def local_music_service(self) -> Any:
        return self._app.local_music_service

    @property
    def music_backend(self) -> Any:
        return self._app.music_backend

    @property
    def runtime_loop(self) -> Any:
        return self._app.runtime_loop

    @property
    def worker_supervisor(self) -> Any:
        return self._app.worker_supervisor

    @property
    def recovery_service(self) -> Any:
        return self._app.recovery_service

    @property
    def power_runtime(self) -> Any:
        return self._app.power_runtime

    @property
    def screen_power_service(self) -> Any:
        return self._app.screen_power_service

    @property
    def scheduler(self) -> Any:
        return self._app.scheduler

    @property
    def bus(self) -> Any:
        return self._app.bus

    @property
    def event_bus(self) -> Any:
        return self._app.bus

    @property
    def context(self) -> Any:
        return self._app.context

    def setup(self) -> bool:
        return bool(self._app.setup())

    def stop(self) -> None:
        self._app.stop()

    @property
    def voip_iterate_interval_seconds(self) -> float:
        runtime_loop = self.runtime_loop
        if runtime_loop is None:
            from yoyopod_cli.pi.validate._navigation_soak.plan import NavigationSoakError

            raise NavigationSoakError("runtime loop is unavailable for navigation soak")
        return float(runtime_loop.configured_voip_iterate_interval_seconds)

    @property
    def screen_timeout_seconds(self) -> float:
        return float(getattr(self._app, "_screen_timeout_seconds", 0.0))

    @property
    def shutdown_completed(self) -> bool:
        return bool(getattr(self._app, "_shutdown_completed", False))

    def simulate_inactivity(self, *, idle_for_seconds: float) -> None:
        setattr(
            self._app,
            "_last_user_activity_at",
            time.monotonic() - max(0.0, idle_for_seconds),
        )


class _NavigationSoakAppFactory(Protocol):
    """Factory for constructing a narrow app handle for soak execution."""

    def __call__(self, *, config_dir: str, simulate: bool) -> _NavigationSoakAppHandle:
        """Create a new app handle for a soak run."""


def _default_app_factory(*, config_dir: str, simulate: bool) -> _NavigationSoakAppHandle:
    """Default app factory used when callers do not provide one."""

    raise NavigationSoakError(
        "navigation soak cannot construct the retired Python app runtime; "
        "provide an explicit app factory"
    )
