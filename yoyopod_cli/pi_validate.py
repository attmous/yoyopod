"""yoyopod_cli/pi_validate.py — staged Pi validation suite."""

from __future__ import annotations

import json
import os
import platform
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Callable, Protocol, cast

import typer

from yoyopod_cli._pi_validate_helpers import (
    NavigationSoakError,
    run_navigation_idle_soak,
    run_navigation_soak,
)
from yoyopod_cli.common import REPO_ROOT, configure_logging, resolve_config_dir
from yoyopod_cli.defaults import DEFAULT_TEST_MUSIC_TARGET_DIR
from yoyopod_cli.paths import load_pi_paths

if TYPE_CHECKING:
    from yoyopod.config import MediaConfig
    from yoyopod_cli.music_fixtures import ProvisionedTestMusicLibrary

app = typer.Typer(
    name="validate",
    help=(
        "Focused target-side validation suite for deploy, smoke, music, voip, "
        "and navigation stability checks."
    ),
    no_args_is_help=True,
)

# ---------------------------------------------------------------------------
# Shared result type (inlined from yoyopod.cli.pi.smoke)
# ---------------------------------------------------------------------------


@dataclass
class _CheckResult:
    """Result for one validation step."""

    name: str
    status: str
    details: str


def _print_summary(name: str, results: list[_CheckResult]) -> None:
    """Print a compact summary table for one validation command."""
    print("")
    print(f"YoyoPod target validation summary: {name}")
    print("=" * 48)
    for result in results:
        print(f"[{result.status.upper():4}] {result.name}: {result.details}")


# ---------------------------------------------------------------------------
# Deploy helpers (inlined from yoyopod.cli.pi.validate)
# ---------------------------------------------------------------------------


def _resolve_runtime_path(path_value: str) -> Path:
    """Resolve one repo-relative or absolute runtime path."""
    path = Path(path_value)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def _nearest_existing_parent(path: Path) -> Path:
    """Return the nearest existing parent for one path."""
    candidate = path if path.exists() and path.is_dir() else path.parent
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _config_files_check(config_path: Path) -> _CheckResult:
    """Validate that the tracked runtime config files are present."""
    required_files = (
        config_path / "app" / "core.yaml",
        config_path / "audio" / "music.yaml",
        config_path / "device" / "hardware.yaml",
        config_path / "voice" / "assistant.yaml",
        config_path / "communication" / "calling.yaml",
        config_path / "communication" / "messaging.yaml",
        config_path / "communication" / "integrations" / "liblinphone_factory.conf",
        config_path / "people" / "directory.yaml",
        config_path / "people" / "contacts.seed.yaml",
    )
    missing = [str(path.relative_to(REPO_ROOT)) for path in required_files if not path.exists()]
    if missing:
        return _CheckResult(
            name="config",
            status="fail",
            details=f"missing required config files: {', '.join(missing)}",
        )

    return _CheckResult(
        name="config",
        status="pass",
        details=", ".join(str(path.relative_to(REPO_ROOT)) for path in required_files),
    )


def _deploy_contract_check() -> tuple[_CheckResult, Any | None]:
    """Validate that the tracked deploy contract is readable."""
    try:
        deploy_config = load_pi_paths()
    except Exception as exc:
        return _CheckResult(name="deploy_contract", status="fail", details=str(exc)), None

    return (
        _CheckResult(
            name="deploy_contract",
            status="pass",
            details=(
                f"project_dir={deploy_config.project_dir}, "
                f"venv={deploy_config.venv}, "
                f"start_cmd={deploy_config.start_cmd}"
            ),
        ),
        deploy_config,
    )


def _runtime_paths_check(deploy_config: Any) -> _CheckResult:
    """Validate that runtime file parents are reachable and writable."""
    path_map = {
        "log": _resolve_runtime_path(deploy_config.log_file),
        "error_log": _resolve_runtime_path(deploy_config.error_log_file),
        "pid": _resolve_runtime_path(deploy_config.pid_file),
        "screenshot": _resolve_runtime_path(deploy_config.screenshot_path),
    }

    details: list[str] = []
    failures: list[str] = []
    for name, path in path_map.items():
        parent = _nearest_existing_parent(path)
        writable = os.access(parent, os.W_OK)
        details.append(f"{name}_parent={parent}")
        if not writable:
            failures.append(f"{name}_parent_not_writable={parent}")

    if failures:
        return _CheckResult(
            name="runtime_paths",
            status="fail",
            details=", ".join(failures),
        )

    return _CheckResult(
        name="runtime_paths",
        status="pass",
        details=", ".join(details),
    )


def _entrypoint_check(deploy_config: Any) -> _CheckResult:
    """Validate repo entrypoints and the configured virtualenv activation path."""
    required_paths = {
        "app": REPO_ROOT / "yoyopod.py",
        "systemd": REPO_ROOT / "deploy" / "systemd" / "yoyopod@.service",
    }

    normalized_venv = Path(deploy_config.venv.rstrip("/"))
    if not normalized_venv.is_absolute():
        normalized_venv = REPO_ROOT / normalized_venv
    activate_path = (
        normalized_venv
        if normalized_venv.name == "activate"
        else normalized_venv / "bin" / "activate"
    )
    required_paths["venv_activate"] = activate_path

    missing = [
        f"{name}={path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path}"
        for name, path in required_paths.items()
        if not path.exists()
    ]
    if missing:
        return _CheckResult(
            name="entrypoints",
            status="fail",
            details=f"missing required paths: {', '.join(missing)}",
        )

    start_parts = shlex.split(deploy_config.start_cmd)
    if not start_parts:
        return _CheckResult(
            name="entrypoints",
            status="fail",
            details="start_cmd is empty in deploy/pi-deploy.yaml",
        )

    executable = start_parts[0]
    resolved_executable = shutil.which(executable)
    if resolved_executable is None:
        return _CheckResult(
            name="entrypoints",
            status="fail",
            details=f"configured start executable is not on PATH: {executable}",
        )

    return _CheckResult(
        name="entrypoints",
        status="pass",
        details=(
            f"start_executable={resolved_executable}, "
            f"venv_activate={activate_path.relative_to(REPO_ROOT) if activate_path.is_relative_to(REPO_ROOT) else activate_path}"
        ),
    )


# ---------------------------------------------------------------------------
# Smoke helpers (inlined from yoyopod.cli.pi.smoke)
# ---------------------------------------------------------------------------


def _load_app_config(config_dir: Path) -> dict[str, Any]:
    """Load the composed app config if present."""
    from loguru import logger

    from yoyopod.config import config_to_dict, load_composed_app_settings

    if not any(
        path.exists()
        for path in (
            config_dir / "app" / "core.yaml",
            config_dir / "device" / "hardware.yaml",
        )
    ):
        logger.warning("Composed app config not found under {}", config_dir)
    return cast(dict[str, Any], config_to_dict(load_composed_app_settings(config_dir)))


def _load_media_config(config_dir: Path) -> MediaConfig:
    """Load the typed composed media config if present."""
    from yoyopod.config import ConfigManager

    return ConfigManager(config_dir=str(config_dir)).get_media_settings()


def _environment_check() -> _CheckResult:
    """Capture the current execution environment."""
    system = platform.system()
    machine = platform.machine()
    python_version = platform.python_version()

    if system == "Linux" and ("arm" in machine.lower() or "aarch" in machine.lower()):
        status = "pass"
    else:
        status = "warn"

    return _CheckResult(
        name="environment",
        status=status,
        details=f"system={system}, machine={machine}, python={python_version}",
    )


def _display_check(
    app_config: dict[str, Any],
    hold_seconds: float,
) -> tuple[_CheckResult, Any]:
    """Validate display initialization on target hardware."""
    from yoyopod.ui.display import Display, detect_hardware

    requested_hardware = str(app_config.get("display", {}).get("hardware", "auto")).lower()
    resolved_hardware = detect_hardware() if requested_hardware == "auto" else requested_hardware

    if resolved_hardware == "simulation":
        return (
            _CheckResult(
                name="display",
                status="fail",
                details=(
                    "hardware detection resolved to simulation; "
                    "no supported Raspberry Pi display hardware was found"
                ),
            ),
            None,
        )

    display = None
    try:
        display = Display(hardware=resolved_hardware, simulate=False)
        adapter = display.get_adapter()

        display.clear(display.COLOR_BLACK)
        display.text("YoyoPod Pi smoke", 10, 40, color=display.COLOR_WHITE, font_size=18)
        display.text("Display OK", 10, 75, color=display.COLOR_GREEN, font_size=18)
        display.update()

        if hold_seconds > 0:
            time.sleep(hold_seconds)

        if display.simulate:
            return (
                _CheckResult(
                    name="display",
                    status="fail",
                    details=(
                        f"adapter {adapter.__class__.__name__} fell back to simulation "
                        "instead of hardware mode"
                    ),
                ),
                display,
            )

        return (
            _CheckResult(
                name="display",
                status="pass",
                details=(
                    f"adapter={adapter.__class__.__name__}, "
                    f"size={display.WIDTH}x{display.HEIGHT}, "
                    f"orientation={display.ORIENTATION}, "
                    f"requested={requested_hardware}, resolved={resolved_hardware}"
                ),
            ),
            display,
        )
    except Exception as exc:
        if display is not None:
            try:
                display.cleanup()
            except Exception:
                pass
        return _CheckResult(name="display", status="fail", details=str(exc)), None


def _input_check(display: Any, app_config: dict[str, Any]) -> _CheckResult:
    """Validate that the matching input adapter can be constructed."""
    from yoyopod.ui.input import get_input_manager

    input_manager = None

    try:
        input_manager = get_input_manager(
            display.get_adapter(),
            config=app_config,
            simulate=False,
        )
        if input_manager is None:
            return _CheckResult(
                name="input",
                status="fail",
                details="no input adapter was created for the detected display hardware",
            )

        capabilities = sorted(action.value for action in input_manager.get_capabilities())
        interaction_profile = input_manager.interaction_profile.value
        input_manager.start()
        time.sleep(0.1)
        input_manager.stop()

        return _CheckResult(
            name="input",
            status="pass",
            details=(f"profile={interaction_profile}, " f"capabilities={', '.join(capabilities)}"),
        )
    except Exception as exc:
        return _CheckResult(name="input", status="fail", details=str(exc))
    finally:
        if input_manager is not None:
            try:
                input_manager.stop()
            except Exception:
                pass


def _power_check(config_dir: Path) -> _CheckResult:
    """Validate PiSugar reachability and report a live battery snapshot."""
    from yoyopod.config import ConfigManager
    from yoyopod.power import PowerManager

    config_manager = ConfigManager(config_dir=str(config_dir))
    manager = PowerManager.from_config_manager(config_manager)

    if not manager.config.enabled:
        return _CheckResult(
            name="power",
            status="warn",
            details="power backend disabled in config/power/backend.yaml",
        )

    snapshot = manager.refresh()
    if not snapshot.available:
        details = snapshot.error or "power backend unavailable"
        return _CheckResult(name="power", status="fail", details=details)

    details = ", ".join(
        [
            f"model={snapshot.device.model or 'unknown'}",
            (
                f"battery={snapshot.battery.level_percent:.1f}%"
                if snapshot.battery.level_percent is not None
                else "battery=unknown"
            ),
            f"charging={snapshot.battery.charging}",
            f"plugged={snapshot.battery.power_plugged}",
        ]
    )
    return _CheckResult(name="power", status="pass", details=details)


def _rtc_check(config_dir: Path) -> _CheckResult:
    """Validate PiSugar RTC reachability and report the current RTC state."""
    from yoyopod.config import ConfigManager
    from yoyopod.power import PowerManager

    config_manager = ConfigManager(config_dir=str(config_dir))
    manager = PowerManager.from_config_manager(config_manager)

    if not manager.config.enabled:
        return _CheckResult(
            name="rtc",
            status="warn",
            details="power backend disabled in config/power/backend.yaml",
        )

    snapshot = manager.refresh()
    if not snapshot.available:
        details = snapshot.error or "power backend unavailable"
        return _CheckResult(name="rtc", status="fail", details=details)

    if snapshot.rtc.time is None:
        return _CheckResult(
            name="rtc",
            status="fail",
            details="PiSugar backend responded but rtc_time is unavailable",
        )

    details = ", ".join(
        [
            f"time={snapshot.rtc.time.isoformat()}",
            f"alarm_enabled={snapshot.rtc.alarm_enabled}",
            f"alarm_time={snapshot.rtc.alarm_time.isoformat() if snapshot.rtc.alarm_time is not None else 'none'}",
            f"repeat_mask={snapshot.rtc.alarm_repeat_mask if snapshot.rtc.alarm_repeat_mask is not None else 'unknown'}",
        ]
    )
    return _CheckResult(name="rtc", status="pass", details=details)


def _music_check(
    media_settings: MediaConfig,
    timeout_seconds: int,
    *,
    expected_library: ProvisionedTestMusicLibrary | None = None,
) -> _CheckResult:
    """Validate music-backend startup and basic state queries."""
    from yoyopod.audio import LocalMusicService, MpvBackend, MusicConfig

    config = MusicConfig.from_media_settings(media_settings)
    backend = MpvBackend(config)
    try:
        started_at = time.monotonic()
        if not backend.start():
            return _CheckResult(
                name="music",
                status="fail",
                details=(
                    "could not start the mpv music backend "
                    f"(binary={config.mpv_binary}, socket={config.mpv_socket})"
                ),
            )

        while not backend.is_connected and (time.monotonic() - started_at) < timeout_seconds:
            time.sleep(0.1)

        if not backend.is_connected:
            return _CheckResult(
                name="music",
                status="fail",
                details=f"music backend did not report ready within {timeout_seconds}s",
            )

        if expected_library is not None:
            missing_assets = [
                path for path in expected_library.expected_asset_paths if not path.exists()
            ]
            if missing_assets:
                missing_list = ", ".join(str(path) for path in missing_assets)
                return _CheckResult(
                    name="music",
                    status="fail",
                    details=f"missing provisioned test assets: {missing_list}",
                )

            music_service = LocalMusicService(backend, music_dir=expected_library.target_dir)
            playlist_path = expected_library.default_playlist_path
            playlists = music_service.list_playlists()
            if str(playlist_path) not in {playlist.uri for playlist in playlists}:
                return _CheckResult(
                    name="music",
                    status="fail",
                    details=f"provisioned playlist not discoverable under {expected_library.target_dir}",
                )

            if not music_service.load_playlist(str(playlist_path)):
                return _CheckResult(
                    name="music",
                    status="fail",
                    details=f"mpv could not load the provisioned playlist {playlist_path}",
                )

            expected_track_uris = {str(path) for path in expected_library.track_paths}
            loaded_track = None
            while (time.monotonic() - started_at) < timeout_seconds:
                loaded_track = backend.get_current_track()
                if loaded_track is not None and loaded_track.uri in expected_track_uris:
                    break
                time.sleep(0.1)

            if loaded_track is None or loaded_track.uri not in expected_track_uris:
                current_uri = loaded_track.uri if loaded_track is not None else "none"
                return _CheckResult(
                    name="music",
                    status="fail",
                    details=(
                        "music backend started, but it did not load one of the "
                        f"provisioned validation tracks from {expected_library.target_dir}; "
                        f"current_track={current_uri}"
                    ),
                )

            playback_state = backend.get_playback_state()
            return _CheckResult(
                name="music",
                status="pass",
                details=(
                    f"binary={config.mpv_binary}, socket={config.mpv_socket}, "
                    f"music_dir={expected_library.target_dir}, "
                    f"playlist={playlist_path.name}, state={playback_state}, "
                    f"track={loaded_track.name}"
                ),
            )

        playback_state = backend.get_playback_state()
        track = backend.get_current_track()
        track_name = track.name if track else "none"

        return _CheckResult(
            name="music",
            status="pass",
            details=(
                f"binary={config.mpv_binary}, socket={config.mpv_socket}, "
                f"state={playback_state}, track={track_name}"
            ),
        )
    except Exception as exc:
        return _CheckResult(name="music", status="fail", details=str(exc))
    finally:
        backend.stop()


def _voip_check(config_dir: Path, registration_timeout: float) -> _CheckResult:
    """Validate Liblinphone startup and SIP registration."""
    from yoyopod.communication.calling.manager import VoIPManager
    from yoyopod.communication.integrations.liblinphone_binding import LiblinphoneBinding
    from yoyopod.communication.models import VoIPConfig
    from yoyopod.config import ConfigManager

    config_manager = ConfigManager(config_dir=str(config_dir))
    voip_config = VoIPConfig.from_config_manager(config_manager)
    binding = LiblinphoneBinding.try_load()
    if binding is None:
        return _CheckResult(
            name="voip",
            status="fail",
            details="Liblinphone shim is unavailable; run yoyopod build liblinphone on the Pi",
        )

    if not voip_config.sip_identity:
        return _CheckResult(
            name="voip",
            status="fail",
            details="sip_identity is empty in config/communication/calling.yaml",
        )

    manager = VoIPManager(
        voip_config,
        people_directory=None,
    )
    try:
        if not manager.start():
            return _CheckResult(
                name="voip",
                status="fail",
                details="VoIP manager failed to start",
            )

        deadline = time.time() + registration_timeout
        last_status = manager.get_status()

        while time.time() < deadline:
            manager.iterate()
            last_status = manager.get_status()
            if last_status["registered"]:
                return _CheckResult(
                    name="voip",
                    status="pass",
                    details=(
                        f"registered={last_status['registered']}, "
                        f"state={last_status['registration_state']}, "
                        f"identity={last_status['sip_identity']}"
                    ),
                )

            if last_status["registration_state"] == "failed":
                break

            time.sleep(0.5)

        return _CheckResult(
            name="voip",
            status="fail",
            details=(
                f"registration timed out or failed; "
                f"state={last_status['registration_state']}, "
                f"identity={last_status['sip_identity']}"
            ),
        )
    except Exception as exc:
        return _CheckResult(name="voip", status="fail", details=str(exc))
    finally:
        manager.stop()


# ---------------------------------------------------------------------------
# VoIP drill helpers (inlined from yoyopod.cli.pi.voip lines 65–481)
# ---------------------------------------------------------------------------

_CONNECTED_CALL_STATES: set[str] = set()  # populated lazily below


def _lazy_connected_call_states() -> set[str]:
    global _CONNECTED_CALL_STATES
    if not _CONNECTED_CALL_STATES:
        from yoyopod.communication.models import CallState

        _CONNECTED_CALL_STATES = {CallState.CONNECTED.value, CallState.STREAMS_RUNNING.value}
    return _CONNECTED_CALL_STATES


class _VoIPManagerLike(Protocol):
    """Minimal manager surface needed by the drill helpers."""

    config: Any
    running: bool

    def start(self) -> bool: ...

    def stop(self) -> None: ...

    def iterate(self) -> int: ...

    def get_status(self) -> dict[str, Any]: ...

    def get_iterate_metrics(self) -> object | None: ...

    def on_registration_change(
        self,
        callback: Callable[[Any], None],
    ) -> None: ...

    def on_call_state_change(
        self,
        callback: Callable[[Any], None],
    ) -> None: ...

    def on_incoming_call(
        self,
        callback: Callable[[str, str], None],
    ) -> None: ...

    def make_call(self, sip_address: str, contact_name: str | None = None) -> bool: ...

    def hangup(self) -> bool: ...

    def get_call_duration(self) -> int: ...


@dataclass(slots=True)
class _DrillResult:
    """One drill outcome and the evidence written to disk."""

    drill: str
    passed: bool
    reason: str
    artifact_dir: Path
    summary_path: Path
    timeline_path: Path
    extras: dict[str, object] = field(default_factory=dict)

    @property
    def status(self) -> str:
        return "pass" if self.passed else "fail"


class _VoIPDrillRecorder:
    """Collect state changes and periodic samples into one timestamped artifact bundle."""

    def __init__(
        self,
        *,
        drill: str,
        config: Any,
        artifacts_dir: str,
        metadata: dict[str, object] | None = None,
        sample_interval_seconds: float = 1.0,
    ) -> None:
        self.drill = drill
        self.config = config
        self.metadata = metadata or {}
        self.started_at_monotonic = time.monotonic()
        self.started_at_unix = time.time()
        self.started_at_iso = self._iso_time(self.started_at_unix)
        self.sample_interval_seconds = max(0.2, sample_interval_seconds)
        self._next_sample_at = self.started_at_monotonic
        artifact_root = self._resolve_artifacts_dir(artifacts_dir)
        run_label = datetime.fromtimestamp(
            self.started_at_unix,
            timezone.utc,
        ).strftime("%Y%m%dT%H%M%SZ")
        self.artifact_dir = artifact_root / f"{drill}-{run_label}"
        self.timeline_path = self.artifact_dir / "timeline.jsonl"
        self.summary_path = self.artifact_dir / "summary.json"
        self.events: list[dict[str, object]] = []
        self.registration_states: list[str] = []
        self.call_states: list[str] = []

    @staticmethod
    def _resolve_artifacts_dir(artifacts_dir: str) -> Path:
        candidate = Path(artifacts_dir)
        if not candidate.is_absolute():
            candidate = REPO_ROOT / candidate
        return candidate

    @staticmethod
    def _iso_time(timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")

    def attach(self, manager: _VoIPManagerLike) -> None:
        manager.on_registration_change(self._on_registration_change)
        manager.on_call_state_change(self._on_call_state_change)

    def _emit(self, kind: str, **payload: object) -> None:
        event = {
            "timestamp": self._iso_time(time.time()),
            "elapsed_seconds": round(max(0.0, time.monotonic() - self.started_at_monotonic), 3),
            "kind": kind,
            **payload,
        }
        self.events.append(event)

    def note(self, message: str) -> None:
        self._emit("note", message=message)

    def checkpoint(self, name: str, **payload: object) -> None:
        self._emit("checkpoint", name=name, **payload)

    def record_command(
        self,
        *,
        phase: str,
        command: str,
        returncode: int,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self._emit(
            "command",
            phase=phase,
            command=command,
            returncode=returncode,
            stdout=stdout.strip(),
            stderr=stderr.strip(),
        )

    def sample(self, manager: _VoIPManagerLike, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now < self._next_sample_at:
            return
        self._emit("sample", status=self._status_snapshot(manager))
        self._next_sample_at = now + self.sample_interval_seconds

    def finalize(
        self,
        *,
        passed: bool,
        reason: str,
        manager: _VoIPManagerLike,
        extras: dict[str, object] | None = None,
    ) -> _DrillResult:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        with self.timeline_path.open("w", encoding="utf-8") as handle:
            for event in self.events:
                handle.write(json.dumps(event, sort_keys=True) + "\n")

        finished_at_unix = time.time()
        resolved_extras: dict[str, object] = extras or {}
        summary = {
            "drill": self.drill,
            "status": "pass" if passed else "fail",
            "reason": reason,
            "started_at": self.started_at_iso,
            "finished_at": self._iso_time(finished_at_unix),
            "duration_seconds": round(
                max(0.0, time.monotonic() - self.started_at_monotonic),
                3,
            ),
            "artifact_dir": str(self.artifact_dir),
            "timeline_path": str(self.timeline_path),
            "final_status": self._status_snapshot(manager),
            "registration_states": self.registration_states,
            "call_states": self.call_states,
            "config": {
                "sip_server": getattr(self.config, "sip_server", ""),
                "sip_identity": getattr(self.config, "sip_identity", ""),
                "iterate_interval_ms": getattr(self.config, "iterate_interval_ms", 0),
            },
            "metadata": self.metadata,
            "extras": resolved_extras,
        }
        with self.summary_path.open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2, sort_keys=True)
            handle.write("\n")

        return _DrillResult(
            drill=self.drill,
            passed=passed,
            reason=reason,
            artifact_dir=self.artifact_dir,
            summary_path=self.summary_path,
            timeline_path=self.timeline_path,
            extras=resolved_extras,
        )

    def _status_snapshot(self, manager: _VoIPManagerLike) -> dict[str, object]:
        status = dict(manager.get_status())
        snapshot: dict[str, object] = {
            "running": bool(status.get("running", False)),
            "registered": bool(status.get("registered", False)),
            "registration_state": str(status.get("registration_state", "")),
            "call_state": str(status.get("call_state", "")),
        }
        get_call_duration = getattr(manager, "get_call_duration", None)
        if callable(get_call_duration):
            snapshot["call_duration_seconds"] = int(get_call_duration())
        metrics = manager.get_iterate_metrics()
        if metrics is not None:
            snapshot["iterate_metrics"] = {
                "native_ms": round(
                    float(getattr(metrics, "native_duration_seconds", 0.0)) * 1000.0,
                    1,
                ),
                "event_drain_ms": round(
                    float(getattr(metrics, "event_drain_duration_seconds", 0.0)) * 1000.0,
                    1,
                ),
                "total_ms": round(
                    float(getattr(metrics, "total_duration_seconds", 0.0)) * 1000.0,
                    1,
                ),
                "drained_events": int(getattr(metrics, "drained_events", 0)),
            }
        return snapshot

    def _on_registration_change(self, state: Any) -> None:
        self.registration_states.append(state.value)
        self._emit("registration", state=state.value)

    def _on_call_state_change(self, state: Any) -> None:
        self.call_states.append(state.value)
        self._emit("call_state", state=state.value)


def _build_voip_manager_for_drill(config_dir: str) -> _VoIPManagerLike:
    from loguru import logger

    from yoyopod.communication.calling.manager import VoIPManager
    from yoyopod.communication.integrations.liblinphone_binding import LiblinphoneBinding
    from yoyopod.communication.models import VoIPConfig
    from yoyopod.config import ConfigManager

    if LiblinphoneBinding.try_load() is None:
        logger.error(
            "Liblinphone shim is unavailable. Build it first with yoyopod build liblinphone."
        )
        raise typer.Exit(code=1)

    config_path = resolve_config_dir(config_dir)
    config_manager = ConfigManager(config_dir=str(config_path))
    voip_config = VoIPConfig.from_config_manager(config_manager)
    return cast(_VoIPManagerLike, VoIPManager(voip_config))


def _iterate_interval_seconds(manager: _VoIPManagerLike) -> float:
    return max(0.01, float(getattr(manager.config, "iterate_interval_ms", 20)) / 1000.0)


def _status_is_registered(status: dict[str, object]) -> bool:
    from yoyopod.communication.models import RegistrationState

    return bool(status.get("registered")) and (
        str(status.get("registration_state")) == RegistrationState.OK.value
    )


def _wait_for_registration_ok(
    manager: _VoIPManagerLike,
    recorder: _VoIPDrillRecorder,
    *,
    timeout: float,
) -> tuple[bool, float]:
    started_at = time.monotonic()
    deadline = started_at + timeout
    interval = _iterate_interval_seconds(manager)
    while time.monotonic() <= deadline:
        manager.iterate()
        recorder.sample(manager)
        if _status_is_registered(manager.get_status()):
            return True, max(0.0, time.monotonic() - started_at)
        time.sleep(interval)
    recorder.sample(manager, force=True)
    return False, max(0.0, time.monotonic() - started_at)


def _wait_for_registration_drop(
    manager: _VoIPManagerLike,
    recorder: _VoIPDrillRecorder,
    *,
    timeout: float,
) -> tuple[bool, str, float]:
    started_at = time.monotonic()
    deadline = started_at + timeout
    interval = _iterate_interval_seconds(manager)
    while time.monotonic() <= deadline:
        manager.iterate()
        recorder.sample(manager)
        status = manager.get_status()
        if not _status_is_registered(status):
            return (
                True,
                str(status.get("registration_state", "")),
                max(0.0, time.monotonic() - started_at),
            )
        time.sleep(interval)
    recorder.sample(manager, force=True)
    return (
        False,
        str(manager.get_status().get("registration_state", "")),
        max(0.0, time.monotonic() - started_at),
    )


def _hold_registration_ok(
    manager: _VoIPManagerLike,
    recorder: _VoIPDrillRecorder,
    *,
    hold_seconds: float,
) -> tuple[bool, str]:
    from yoyopod.communication.models import RegistrationState

    deadline = time.monotonic() + hold_seconds
    interval = _iterate_interval_seconds(manager)
    while time.monotonic() <= deadline:
        manager.iterate()
        recorder.sample(manager)
        status = manager.get_status()
        if not _status_is_registered(status):
            return False, str(status.get("registration_state", ""))
        time.sleep(interval)
    recorder.sample(manager, force=True)
    return True, RegistrationState.OK.value


def _wait_for_call_connection(
    manager: _VoIPManagerLike,
    recorder: _VoIPDrillRecorder,
    *,
    timeout: float,
) -> tuple[bool, str, float]:
    from yoyopod.communication.models import CallState

    started_at = time.monotonic()
    deadline = started_at + timeout
    interval = _iterate_interval_seconds(manager)
    terminal_states = {
        CallState.IDLE.value,
        CallState.RELEASED.value,
        CallState.END.value,
        CallState.ERROR.value,
    }
    connected_states = _lazy_connected_call_states()
    while time.monotonic() <= deadline:
        manager.iterate()
        recorder.sample(manager)
        status = manager.get_status()
        call_state = str(status.get("call_state", ""))
        if call_state in connected_states:
            return True, call_state, max(0.0, time.monotonic() - started_at)
        if call_state in terminal_states:
            return False, call_state, max(0.0, time.monotonic() - started_at)
        time.sleep(interval)
    recorder.sample(manager, force=True)
    return (
        False,
        str(manager.get_status().get("call_state", "")),
        max(0.0, time.monotonic() - started_at),
    )


def _hold_call_connected(
    manager: _VoIPManagerLike,
    recorder: _VoIPDrillRecorder,
    *,
    soak_seconds: float,
) -> tuple[bool, str]:
    deadline = time.monotonic() + soak_seconds
    interval = _iterate_interval_seconds(manager)
    connected_states = _lazy_connected_call_states()
    while time.monotonic() <= deadline:
        manager.iterate()
        recorder.sample(manager)
        status = manager.get_status()
        if not _status_is_registered(status):
            return False, f"registration_state={status.get('registration_state', '')}"
        call_state = str(status.get("call_state", ""))
        if call_state not in connected_states:
            return False, f"call_state={call_state}"
        time.sleep(interval)
    recorder.sample(manager, force=True)
    return True, ""


def _wait_for_call_end(
    manager: _VoIPManagerLike,
    recorder: _VoIPDrillRecorder,
    *,
    timeout: float,
) -> tuple[bool, str, float]:
    from yoyopod.communication.models import CallState

    started_at = time.monotonic()
    deadline = started_at + timeout
    interval = _iterate_interval_seconds(manager)
    terminal_states = {
        CallState.IDLE.value,
        CallState.RELEASED.value,
        CallState.END.value,
        CallState.ERROR.value,
    }
    while time.monotonic() <= deadline:
        manager.iterate()
        recorder.sample(manager)
        status = manager.get_status()
        call_state = str(status.get("call_state", ""))
        if call_state in terminal_states:
            return True, call_state, max(0.0, time.monotonic() - started_at)
        time.sleep(interval)
    recorder.sample(manager, force=True)
    return (
        False,
        str(manager.get_status().get("call_state", "")),
        max(0.0, time.monotonic() - started_at),
    )


def _run_shell_hook(
    *,
    recorder: _VoIPDrillRecorder,
    phase: str,
    command: str,
) -> bool:
    """Run an operator-supplied outage hook.

    The reconnect drill treats --drop-command/--restore-command as trusted operator input
    for a local diagnostic workflow on the device, so shell execution is intentional here.
    """
    completed = subprocess.run(
        command,
        shell=True,
        check=False,
        capture_output=True,
        text=True,
    )
    recorder.record_command(
        phase=phase,
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    return completed.returncode == 0


def _print_drill_result(result: _DrillResult) -> None:
    print("")
    print(f"VoIP drill result: {result.drill}")
    print("=" * 48)
    print(f"status={result.status}")
    print(f"reason={result.reason}")
    for key, value in sorted(result.extras.items()):
        print(f"{key}={value}")
    print(f"artifact_dir={result.artifact_dir}")
    print(f"summary={result.summary_path}")
    print(f"timeline={result.timeline_path}")


# ---------------------------------------------------------------------------
# VoIP soak private runners (converted from @voip_app.command bodies)
# ---------------------------------------------------------------------------


def _run_quick_voip_check(config_dir: str, registration_timeout: float) -> None:
    """Run the quick VoIP registration validation (no soak)."""
    config_path = resolve_config_dir(config_dir)
    results = [_voip_check(config_path, registration_timeout)]
    _print_summary("voip", results)
    if any(result.status == "fail" for result in results):
        raise typer.Exit(code=1)


def _run_voip_registration_stability(
    config_dir: str,
    registration_timeout: float,
    hold_seconds: float,
    artifacts_dir: str,
    sample_interval: float,
) -> None:
    """Hold SIP registration open long enough to catch immediate flapping on hardware."""
    from loguru import logger

    manager = _build_voip_manager_for_drill(config_dir)
    recorder = _VoIPDrillRecorder(
        drill="registration-stability",
        config=manager.config,
        artifacts_dir=artifacts_dir,
        metadata={
            "registration_timeout": registration_timeout,
            "hold_seconds": hold_seconds,
        },
        sample_interval_seconds=sample_interval,
    )
    recorder.attach(manager)

    try:
        if not manager.start():
            result = recorder.finalize(
                passed=False,
                reason="VoIP manager failed to start",
                manager=manager,
            )
            _print_drill_result(result)
            raise typer.Exit(code=1)

        logger.info("Waiting for SIP registration to stabilize")
        registered, registration_seconds = _wait_for_registration_ok(
            manager,
            recorder,
            timeout=registration_timeout,
        )
        if not registered:
            result = recorder.finalize(
                passed=False,
                reason="Registration never reached OK",
                manager=manager,
                extras={"registration_wait_seconds": round(registration_seconds, 3)},
            )
            _print_drill_result(result)
            raise typer.Exit(code=1)

        recorder.checkpoint(
            "registration_ok",
            registration_wait_seconds=round(registration_seconds, 3),
        )
        stable, failed_state = _hold_registration_ok(
            manager,
            recorder,
            hold_seconds=hold_seconds,
        )
        result = recorder.finalize(
            passed=stable,
            reason=(
                f"Registration stayed OK for {hold_seconds:.1f}s"
                if stable
                else f"Registration left OK during stability hold: {failed_state}"
            ),
            manager=manager,
            extras={
                "registration_wait_seconds": round(registration_seconds, 3),
                "hold_seconds": hold_seconds,
                "failed_state": failed_state,
            },
        )
        _print_drill_result(result)
        if not stable:
            raise typer.Exit(code=1)
    finally:
        manager.stop()


def _run_voip_reconnect_drill(
    config_dir: str,
    registration_timeout: float,
    disconnect_seconds: float,
    drop_detect_timeout: float,
    recovery_timeout: float,
    drop_command: str,
    restore_command: str,
    artifacts_dir: str,
    sample_interval: float,
) -> None:
    """Verify that SIP registration drops and then recovers after a short network wobble."""
    from loguru import logger

    from yoyopod.communication.models import RegistrationState

    manager = _build_voip_manager_for_drill(config_dir)
    recorder = _VoIPDrillRecorder(
        drill="reconnect-drill",
        config=manager.config,
        artifacts_dir=artifacts_dir,
        metadata={
            "registration_timeout": registration_timeout,
            "disconnect_seconds": disconnect_seconds,
            "drop_detect_timeout": drop_detect_timeout,
            "recovery_timeout": recovery_timeout,
            "drop_command": drop_command,
            "restore_command": restore_command,
        },
        sample_interval_seconds=sample_interval,
    )
    recorder.attach(manager)

    try:
        if not manager.start():
            result = recorder.finalize(
                passed=False,
                reason="VoIP manager failed to start",
                manager=manager,
            )
            _print_drill_result(result)
            raise typer.Exit(code=1)

        registered, registration_seconds = _wait_for_registration_ok(
            manager,
            recorder,
            timeout=registration_timeout,
        )
        if not registered:
            result = recorder.finalize(
                passed=False,
                reason="Initial registration never reached OK",
                manager=manager,
                extras={"registration_wait_seconds": round(registration_seconds, 3)},
            )
            _print_drill_result(result)
            raise typer.Exit(code=1)

        recorder.checkpoint(
            "initial_registration_ok",
            registration_wait_seconds=round(registration_seconds, 3),
        )
        if drop_command:
            logger.info("Running network drop hook")
            if not _run_shell_hook(recorder=recorder, phase="drop", command=drop_command):
                result = recorder.finalize(
                    passed=False,
                    reason="The configured network drop command failed",
                    manager=manager,
                )
                _print_drill_result(result)
                raise typer.Exit(code=1)
        else:
            message = (
                f"Drop network connectivity now for about {disconnect_seconds:.1f}s, "
                "then restore it. The drill is recording registration loss and recovery."
            )
            logger.info(message)
            recorder.note(message)

        outage_started_at = time.monotonic()
        outage_deadline = outage_started_at + disconnect_seconds
        drop_observed = False
        drop_state = RegistrationState.OK.value
        first_drop_wait_seconds: float | None = None
        while time.monotonic() <= outage_deadline:
            manager.iterate()
            recorder.sample(manager)
            status = manager.get_status()
            if not _status_is_registered(status):
                drop_observed = True
                drop_state = str(status.get("registration_state", ""))
                if first_drop_wait_seconds is None:
                    first_drop_wait_seconds = max(0.0, time.monotonic() - outage_started_at)
            time.sleep(_iterate_interval_seconds(manager))

        if restore_command:
            logger.info("Running network restore hook")
            if not _run_shell_hook(recorder=recorder, phase="restore", command=restore_command):
                result = recorder.finalize(
                    passed=False,
                    reason="The configured network restore command failed",
                    manager=manager,
                    extras={"drop_observed": drop_observed, "drop_state": drop_state},
                )
                _print_drill_result(result)
                raise typer.Exit(code=1)
        elif drop_command:
            logger.info("Restore network connectivity now so SIP registration can recover")
            recorder.note("Restore network connectivity now so SIP registration can recover.")

        if not drop_observed:
            drop_observed, drop_state, drop_wait_seconds = _wait_for_registration_drop(
                manager,
                recorder,
                timeout=drop_detect_timeout,
            )
        else:
            assert first_drop_wait_seconds is not None
            drop_wait_seconds = first_drop_wait_seconds

        if not drop_observed:
            result = recorder.finalize(
                passed=False,
                reason="Registration never left OK during the reconnect drill",
                manager=manager,
                extras={
                    "registration_wait_seconds": round(registration_seconds, 3),
                    "drop_wait_seconds": round(drop_wait_seconds, 3),
                    "drop_state": drop_state,
                },
            )
            _print_drill_result(result)
            raise typer.Exit(code=1)

        recorder.checkpoint(
            "registration_dropped",
            drop_wait_seconds=round(drop_wait_seconds, 3),
            drop_state=drop_state,
        )
        recovered, recovery_seconds = _wait_for_registration_ok(
            manager,
            recorder,
            timeout=recovery_timeout,
        )
        result = recorder.finalize(
            passed=recovered,
            reason=(
                "Registration recovered after the temporary outage"
                if recovered
                else "Registration did not recover after the temporary outage"
            ),
            manager=manager,
            extras={
                "registration_wait_seconds": round(registration_seconds, 3),
                "drop_wait_seconds": round(drop_wait_seconds, 3),
                "drop_state": drop_state,
                "recovery_wait_seconds": round(recovery_seconds, 3),
            },
        )
        _print_drill_result(result)
        if not recovered:
            raise typer.Exit(code=1)
    finally:
        manager.stop()


def _run_voip_call_soak(
    config_dir: str,
    target: str,
    contact_name: str,
    registration_timeout: float,
    connect_timeout: float,
    soak_seconds: float,
    hangup_timeout: float,
    artifacts_dir: str,
    sample_interval: float,
) -> None:
    """Place one real call, wait for connection, and hold it long enough to catch drift."""
    from loguru import logger

    manager = _build_voip_manager_for_drill(config_dir)
    recorder = _VoIPDrillRecorder(
        drill="call-soak",
        config=manager.config,
        artifacts_dir=artifacts_dir,
        metadata={
            "target": target,
            "contact_name": contact_name,
            "registration_timeout": registration_timeout,
            "connect_timeout": connect_timeout,
            "soak_seconds": soak_seconds,
            "hangup_timeout": hangup_timeout,
        },
        sample_interval_seconds=sample_interval,
    )
    recorder.attach(manager)

    try:
        if not manager.start():
            result = recorder.finalize(
                passed=False,
                reason="VoIP manager failed to start",
                manager=manager,
            )
            _print_drill_result(result)
            raise typer.Exit(code=1)

        registered, registration_seconds = _wait_for_registration_ok(
            manager,
            recorder,
            timeout=registration_timeout,
        )
        if not registered:
            result = recorder.finalize(
                passed=False,
                reason="Registration never reached OK before the call soak",
                manager=manager,
                extras={"registration_wait_seconds": round(registration_seconds, 3)},
            )
            _print_drill_result(result)
            raise typer.Exit(code=1)

        if not manager.make_call(target, contact_name or None):
            result = recorder.finalize(
                passed=False,
                reason=f"Failed to initiate call to {target}",
                manager=manager,
                extras={"registration_wait_seconds": round(registration_seconds, 3)},
            )
            _print_drill_result(result)
            raise typer.Exit(code=1)

        logger.info("Waiting for the call to connect: {}", target)
        connected, connected_state, connect_seconds = _wait_for_call_connection(
            manager,
            recorder,
            timeout=connect_timeout,
        )
        if not connected:
            result = recorder.finalize(
                passed=False,
                reason=f"Call never reached a connected state (last_state={connected_state})",
                manager=manager,
                extras={
                    "target": target,
                    "registration_wait_seconds": round(registration_seconds, 3),
                    "connect_wait_seconds": round(connect_seconds, 3),
                    "last_call_state": connected_state,
                },
            )
            _print_drill_result(result)
            raise typer.Exit(code=1)

        recorder.checkpoint(
            "call_connected",
            target=target,
            connect_wait_seconds=round(connect_seconds, 3),
            connected_state=connected_state,
        )
        soaked, soak_failure = _hold_call_connected(
            manager,
            recorder,
            soak_seconds=soak_seconds,
        )
        cleanup_reason = "cleanup_skipped"
        if manager.hangup():
            hangup_ok, hangup_state, hangup_seconds = _wait_for_call_end(
                manager,
                recorder,
                timeout=hangup_timeout,
            )
            cleanup_reason = (
                f"hangup_wait_seconds={round(hangup_seconds, 3)} last_state={hangup_state}"
                if not hangup_ok
                else "hangup_clean"
            )
        result = recorder.finalize(
            passed=soaked,
            reason=(
                f"Call stayed connected for {soak_seconds:.1f}s"
                if soaked
                else f"Call soak failed: {soak_failure}"
            ),
            manager=manager,
            extras={
                "target": target,
                "registration_wait_seconds": round(registration_seconds, 3),
                "connect_wait_seconds": round(connect_seconds, 3),
                "soak_seconds": soak_seconds,
                "cleanup": cleanup_reason,
            },
        )
        _print_drill_result(result)
        if not soaked:
            raise typer.Exit(code=1)
    finally:
        manager.stop()


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


@app.command()
def deploy(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to validate.")
    ] = "config",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Validate deploy-readiness for the current target checkout without launching the app."""
    from loguru import logger

    configure_logging(verbose)
    config_path = resolve_config_dir(config_dir)

    logger.info("Running target deploy validation")

    deploy_result, deploy_config = _deploy_contract_check()
    results = [deploy_result, _config_files_check(config_path)]
    if deploy_config is not None:
        results.append(_runtime_paths_check(deploy_config))
        results.append(_entrypoint_check(deploy_config))

    _print_summary("deploy", results)
    if any(result.status == "fail" for result in results):
        raise typer.Exit(code=1)


@app.command()
def smoke(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    with_power: Annotated[
        bool, typer.Option("--with-power", help="Also validate PiSugar power telemetry.")
    ] = False,
    with_rtc: Annotated[
        bool, typer.Option("--with-rtc", help="Also validate PiSugar RTC state and alarm.")
    ] = False,
    display_hold_seconds: Annotated[
        float,
        typer.Option(
            "--display-hold-seconds",
            help="How long to keep the display confirmation text visible.",
        ),
    ] = 0.5,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Validate core target hardware paths: environment, display, input, and optional PiSugar state."""
    from loguru import logger

    configure_logging(verbose)
    config_path = resolve_config_dir(config_dir)

    logger.info("Running target smoke validation")

    app_config = _load_app_config(config_path)
    results: list[_CheckResult] = [_environment_check()]
    display = None

    try:
        display_result, display = _display_check(app_config, display_hold_seconds)
        results.append(display_result)

        if display_result.status == "pass" and display is not None:
            results.append(_input_check(display, app_config))

        if with_power:
            results.append(_power_check(config_path))

        if with_rtc:
            results.append(_rtc_check(config_path))
    finally:
        if display is not None:
            try:
                display.cleanup()
            except Exception as exc:
                logger.warning(f"Display cleanup failed: {exc}")

    _print_summary("smoke", results)
    if any(result.status == "fail" for result in results):
        raise typer.Exit(code=1)


@app.command()
def music(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    timeout: Annotated[
        int, typer.Option("--timeout", help="Startup timeout in seconds for the music backend.")
    ] = 5,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Validate the mpv music backend on the target without starting the full app."""
    from loguru import logger

    configure_logging(verbose)
    config_path = resolve_config_dir(config_dir)

    logger.info("Running target music validation")

    media_config = _load_media_config(config_path)
    results = [_music_check(media_config, timeout)]

    _print_summary("music", results)
    if any(result.status == "fail" for result in results):
        raise typer.Exit(code=1)


@app.command()
def voip(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    registration_timeout: Annotated[
        float, typer.Option("--registration-timeout", help="Registration timeout in seconds.")
    ] = 90.0,
    soak: Annotated[
        str,
        typer.Option(
            "--soak",
            help="Optional soak mode: registration | reconnect | call",
        ),
    ] = "",
    # registration-soak options
    hold_seconds: Annotated[
        float,
        typer.Option(
            "--hold-seconds", help="How long SIP registration must remain OK after startup."
        ),
    ] = 60.0,
    # reconnect-soak options
    disconnect_seconds: Annotated[
        float,
        typer.Option(
            "--disconnect-seconds", help="How long the temporary network outage should last."
        ),
    ] = 8.0,
    drop_detect_timeout: Annotated[
        float,
        typer.Option(
            "--drop-detect-timeout",
            help="How long to wait for registration to leave OK after the outage starts.",
        ),
    ] = 20.0,
    recovery_timeout: Annotated[
        float,
        typer.Option(
            "--recovery-timeout",
            help="How long to wait for SIP registration to recover after the outage.",
        ),
    ] = 45.0,
    drop_command: Annotated[
        str,
        typer.Option(
            "--drop-command",
            help="Optional shell command that intentionally drops network connectivity on the Pi.",
        ),
    ] = "",
    restore_command: Annotated[
        str,
        typer.Option(
            "--restore-command",
            help="Optional shell command that restores network connectivity on the Pi.",
        ),
    ] = "",
    # call-soak options
    soak_target: Annotated[
        str,
        typer.Option(
            "--soak-target",
            help="SIP address to call for the call soak drill, for example sip:echo@example.com.",
        ),
    ] = "",
    soak_contact_name: Annotated[
        str,
        typer.Option(
            "--soak-contact-name",
            help="Optional contact label used for log output while making the call.",
        ),
    ] = "",
    soak_seconds: Annotated[
        float,
        typer.Option(
            "--soak-seconds", help="How long the call must remain connected once media is up."
        ),
    ] = 300.0,
    connect_timeout: Annotated[
        float,
        typer.Option(
            "--connect-timeout",
            help="How long to wait for the target call to reach a connected media state.",
        ),
    ] = 60.0,
    hangup_timeout: Annotated[
        float,
        typer.Option(
            "--hangup-timeout",
            help="How long to wait for the call to tear down cleanly after the soak.",
        ),
    ] = 15.0,
    # shared soak options
    artifacts_dir: Annotated[
        str,
        typer.Option(
            "--artifacts-dir", help="Directory where timestamped drill artifacts should be written."
        ),
    ] = "logs/voip-validation",
    sample_interval: Annotated[
        float,
        typer.Option(
            "--sample-interval",
            help="How often to capture periodic status samples into the timeline.",
        ),
    ] = 1.0,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """VoIP validation: quick check (default) or soak drill (--soak registration|reconnect|call)."""
    configure_logging(verbose)
    if not soak:
        return _run_quick_voip_check(config_dir, registration_timeout)
    if soak == "registration":
        return _run_voip_registration_stability(
            config_dir,
            registration_timeout,
            hold_seconds,
            artifacts_dir,
            sample_interval,
        )
    if soak == "reconnect":
        return _run_voip_reconnect_drill(
            config_dir,
            registration_timeout,
            disconnect_seconds,
            drop_detect_timeout,
            recovery_timeout,
            drop_command,
            restore_command,
            artifacts_dir,
            sample_interval,
        )
    if soak == "call":
        if not soak_target:
            raise typer.BadParameter("--soak call requires --soak-target")
        return _run_voip_call_soak(
            config_dir,
            soak_target,
            soak_contact_name,
            registration_timeout,
            connect_timeout,
            soak_seconds,
            hangup_timeout,
            artifacts_dir,
            sample_interval,
        )
    raise typer.BadParameter(
        f"unknown --soak value: {soak!r}; expected registration, reconnect, or call"
    )


@app.command()
def stability(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    cycles: Annotated[
        int, typer.Option("--cycles", help="How many full transition cycles to run.")
    ] = 2,
    hold_seconds: Annotated[
        float,
        typer.Option("--hold-seconds", help="How long to keep each screen active during the soak."),
    ] = 0.2,
    idle_seconds: Annotated[
        float,
        typer.Option("--idle-seconds", help="How long to idle after each full navigation cycle."),
    ] = 1.0,
    with_music: Annotated[
        bool,
        typer.Option(
            "--with-music",
            help="Also exercise playlist loading and now-playing actions during the soak.",
        ),
    ] = False,
    provision_test_music: Annotated[
        bool,
        typer.Option(
            "--provision-test-music/--no-provision-test-music",
            help="Seed deterministic validation music before playback soak steps.",
        ),
    ] = True,
    test_music_dir: Annotated[
        str,
        typer.Option(
            "--test-music-dir",
            help="Dedicated target directory for validation-only test music assets.",
        ),
    ] = "",
    skip_sleep: Annotated[
        bool, typer.Option("--skip-sleep", help="Skip the sleep and wake exercise.")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Run a repeated navigation and idle stability pass on the target checkout."""
    configure_logging(verbose)
    resolved_music_dir = test_music_dir or DEFAULT_TEST_MUSIC_TARGET_DIR
    try:
        report = run_navigation_idle_soak(
            config_dir=config_dir,
            simulate=False,
            cycles=cycles,
            hold_seconds=hold_seconds,
            idle_seconds=idle_seconds,
            skip_sleep=skip_sleep,
            with_music=with_music,
            provision_test_music=provision_test_music,
            test_music_dir=resolved_music_dir,
        )
    except NavigationSoakError as exc:
        from loguru import logger

        logger.error(f"Stability soak failed: {exc}")
        raise typer.Exit(code=1)

    from loguru import logger

    logger.info(f"Stability soak passed: {report.summary()}")


@app.command()
def navigation(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    cycles: Annotated[
        int, typer.Option("--cycles", help="How many full navigation cycles to run.")
    ] = 2,
    hold_seconds: Annotated[
        float,
        typer.Option(
            "--hold-seconds",
            help="How long to pump after each simulated click or route change.",
        ),
    ] = 0.35,
    idle_seconds: Annotated[
        float,
        typer.Option(
            "--idle-seconds",
            help="How long to leave each exercised screen idle before the next action.",
        ),
    ] = 3.0,
    tail_idle_seconds: Annotated[
        float,
        typer.Option(
            "--tail-idle-seconds",
            help="Final idle dwell on the hub after all navigation cycles complete.",
        ),
    ] = 10.0,
    with_playback: Annotated[
        bool,
        typer.Option(
            "--with-playback/--no-with-playback",
            help="Drive playlist and shuffle playback paths during the soak.",
        ),
    ] = True,
    provision_test_music: Annotated[
        bool,
        typer.Option(
            "--provision-test-music/--no-provision-test-music",
            help="Seed deterministic validation music before playback-driven navigation.",
        ),
    ] = True,
    test_music_dir: Annotated[
        str,
        typer.Option(
            "--test-music-dir",
            help="Dedicated target directory for validation-only test music assets.",
        ),
    ] = "",
    skip_sleep: Annotated[
        bool, typer.Option("--skip-sleep", help="Skip the final sleep/wake exercise.")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Run the one-button target navigation and idle stability soak on LVGL hardware."""
    from loguru import logger

    configure_logging(verbose)
    resolved_music_dir = test_music_dir or DEFAULT_TEST_MUSIC_TARGET_DIR

    ok, details = run_navigation_soak(
        config_dir=config_dir,
        cycles=cycles,
        hold_seconds=hold_seconds,
        idle_seconds=idle_seconds,
        tail_idle_seconds=tail_idle_seconds,
        with_playback=with_playback,
        provision_test_music=provision_test_music,
        test_music_dir=resolved_music_dir,
        skip_sleep=skip_sleep,
    )
    if ok:
        logger.info("Navigation soak passed: {}", details)
        return

    logger.error("Navigation soak failed: {}", details)
    raise typer.Exit(code=1)


@app.command()
def lvgl(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    simulate: Annotated[
        bool, typer.Option("--simulate", help="Run against simulation instead of hardware.")
    ] = False,
    cycles: Annotated[
        int, typer.Option("--cycles", help="How many full transition cycles to run.")
    ] = 2,
    hold_seconds: Annotated[
        float,
        typer.Option("--hold-seconds", help="How long to keep each screen active during the soak."),
    ] = 0.2,
    idle_seconds: Annotated[
        float,
        typer.Option("--idle-seconds", help="How long to idle after each full navigation cycle."),
    ] = 1.0,
    with_music: Annotated[
        bool,
        typer.Option(
            "--with-music",
            help="Exercise playlist loading and now-playing actions during the soak.",
        ),
    ] = False,
    provision_test_music: Annotated[
        bool,
        typer.Option(
            "--provision-test-music/--no-provision-test-music",
            help="Seed the deterministic validation music library before playback soak steps.",
        ),
    ] = True,
    test_music_dir: Annotated[
        str,
        typer.Option(
            "--test-music-dir",
            help="Dedicated target directory for validation-only test music assets.",
        ),
    ] = "",
    skip_sleep: Annotated[
        bool, typer.Option("--skip-sleep", help="Skip the sleep/wake exercise.")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Run a deterministic LVGL navigation and idle soak pass against YoyoPod."""
    from loguru import logger

    configure_logging(verbose)
    resolved_music_dir = test_music_dir or DEFAULT_TEST_MUSIC_TARGET_DIR
    try:
        report = run_navigation_idle_soak(
            config_dir=config_dir,
            simulate=simulate,
            cycles=cycles,
            hold_seconds=hold_seconds,
            idle_seconds=idle_seconds,
            skip_sleep=skip_sleep,
            with_music=with_music,
            provision_test_music=provision_test_music,
            test_music_dir=resolved_music_dir,
        )
    except NavigationSoakError as exc:
        logger.error(f"LVGL soak failed: {exc}")
        raise typer.Exit(code=1)
    logger.info(f"LVGL soak passed: {report.summary()}")
