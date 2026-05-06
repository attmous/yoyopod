"""Rust VoIP runtime helpers for on-device diagnostics."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

from yoyopod_cli.common import REPO_ROOT, resolve_config_dir
from yoyopod_cli.pi.support.bus import Bus
from yoyopod_cli.pi.support.call_models import VoIPConfig
from yoyopod_cli.pi.support.events import (
    WorkerDomainStateChangedEvent,
    WorkerMessageReceivedEvent,
)
from yoyopod_cli.pi.support.scheduler import MainThreadScheduler
from yoyopod_cli.pi.support.voip_manager import VoIPManager
from yoyopod_cli.pi.support.workers import WorkerSupervisor


def rust_voip_worker_path() -> str:
    return os.environ.get(
        "YOYOPOD_RUST_VOIP_HOST_WORKER",
        "device/voip/build/yoyopod-voip-host",
    ).strip()


def assert_rust_voip_artifacts_present() -> None:
    missing: list[Path] = []
    worker_path = Path(rust_voip_worker_path())
    if not worker_path.is_absolute():
        worker_path = REPO_ROOT / worker_path
    if not worker_path.is_file():
        missing.append(worker_path)
    if missing:
        details = "\n".join(f"- {path}" for path in missing)
        raise RuntimeError(
            "Rust VoIP host artifact is missing. Download the GitHub Actions artifact "
            "for the exact commit under test; do not build Rust binaries on the Pi.\n"
            f"{details}"
        )


class RustVoIPDiagnosticManager:
    """VoIPManager wrapper that also pumps Rust worker supervisor events."""

    def __init__(
        self,
        *,
        manager: VoIPManager,
        worker_supervisor: WorkerSupervisor,
        scheduler: MainThreadScheduler,
        bus: Bus,
    ) -> None:
        self._manager = manager
        self._worker_supervisor = worker_supervisor
        self._scheduler = scheduler
        self._bus = bus

    def __getattr__(self, name: str) -> Any:
        return getattr(self._manager, name)

    @property
    def config(self) -> VoIPConfig:
        return cast(VoIPConfig, self._manager.config)

    @property
    def running(self) -> bool:
        return self._manager.running

    def start(self) -> bool:
        return self._manager.start()

    def stop(self) -> None:
        self._manager.stop()
        self._worker_supervisor.stop_all(grace_seconds=1.0)

    def iterate(self) -> int:
        drained = int(self._manager.iterate() or 0)
        drained += int(self._worker_supervisor.poll() or 0)
        drained += int(self._bus.drain() or 0)
        drained += int(self._scheduler.drain() or 0)
        return drained


def build_rust_voip_manager(config_dir: str) -> RustVoIPDiagnosticManager:
    from yoyopod_cli.pi.support.voip_backend.rust_host import RustHostBackend
    from yoyopod_cli.config import ConfigManager

    assert_rust_voip_artifacts_present()

    config_path = resolve_config_dir(config_dir)
    config_manager = ConfigManager(config_dir=str(config_path))
    voip_config = VoIPConfig.from_config_manager(config_manager)

    scheduler = MainThreadScheduler()
    bus = Bus()
    worker_supervisor = WorkerSupervisor(scheduler=scheduler, bus=bus)
    backend_config = cast(Any, voip_config)
    backend = RustHostBackend(
        backend_config,
        worker_supervisor=worker_supervisor,
        worker_path=rust_voip_worker_path(),
        cwd=str(REPO_ROOT),
    )
    bus.subscribe(WorkerMessageReceivedEvent, backend.handle_worker_message)
    bus.subscribe(WorkerDomainStateChangedEvent, backend.handle_worker_state_change)
    manager = VoIPManager(
        backend_config,
        backend=backend,
        event_scheduler=scheduler.run_on_main,
        background_iterate_enabled=False,
    )
    return RustVoIPDiagnosticManager(
        manager=manager,
        worker_supervisor=worker_supervisor,
        scheduler=scheduler,
        bus=bus,
    )
