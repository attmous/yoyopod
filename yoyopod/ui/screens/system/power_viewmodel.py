"""Viewmodel builders for the Setup screen."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from yoyopod.integrations.power import PowerManager
    from yoyopod.integrations.power.models import PowerSnapshot


@dataclass(frozen=True, slots=True)
class PowerScreenState:
    """Prepared power/setup state consumed by the Setup screen."""

    snapshot: "PowerSnapshot | None" = None
    status: dict[str, object] = field(default_factory=dict)
    network_enabled: bool = False
    network_rows: tuple[tuple[str, str], ...] = ()
    gps_rows: tuple[tuple[str, str], ...] = ()
    playback_devices: tuple[str, ...] = ()
    capture_devices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PowerScreenActions:
    """Focused actions exposed to the Setup screen."""

    refresh_voice_devices: Callable[[], None] | None = None
    refresh_gps: Callable[[], bool] | None = None
    persist_speaker_device: Callable[[str | None], bool] | None = None
    persist_capture_device: Callable[[str | None], bool] | None = None
    volume_up: Callable[[int], int | None] | None = None
    volume_down: Callable[[int], int | None] | None = None
    mute: Callable[[], bool] | None = None
    unmute: Callable[[], bool] | None = None


_VOICE_PAGE_SIGNATURE_FIELDS = (
    "commands_enabled",
    "ai_requests_enabled",
    "screen_read_enabled",
    "speaker_device_id",
    "capture_device_id",
    "mic_muted",
    "output_volume",
)


def _disabled_gps_rows() -> list[tuple[str, str]]:
    return [
        ("Fix", "Disabled"),
        ("Lat", "--"),
        ("Lng", "--"),
        ("Alt", "--"),
        ("Speed", "--"),
    ]


def _runtime_snapshot(network_runtime: object | None) -> object | None:
    if network_runtime is None:
        return None
    snapshot = getattr(network_runtime, "snapshot", None)
    if not callable(snapshot):
        return None
    return snapshot()


def _build_network_rows_from_runtime(network_runtime: object | None) -> list[tuple[str, str]]:
    """Build cellular rows from the Rust-owned network snapshot."""

    snapshot = _runtime_snapshot(network_runtime)
    if snapshot is None or not getattr(snapshot, "enabled", False):
        return [("Status", "Disabled")]

    state = str(getattr(snapshot, "state", "") or "").strip()
    connected = bool(getattr(snapshot, "connected", False))
    if connected:
        status_text = "Online"
    elif state in {"registered", "ppp_starting", "ppp_stopping"}:
        status_text = "Registered"
    elif state in {"probing", "ready", "registering", "recovering"}:
        status_text = "Connecting"
    elif state == "degraded":
        status_text = "Degraded"
    else:
        status_text = "Offline"

    signal = getattr(snapshot, "signal", None)
    signal_bars = max(0, min(4, int(getattr(signal, "bars", 0) or 0)))
    signal_text = "Unknown"
    if signal is not None and (getattr(signal, "csq", None) is not None or signal_bars > 0):
        signal_text = f"{signal_bars}/4"

    return [
        ("Status", status_text),
        ("Carrier", str(getattr(snapshot, "carrier", "") or "Unknown")),
        ("Type", str(getattr(snapshot, "network_type", "") or "Unknown")),
        ("Signal", signal_text),
        ("PPP", "Up" if connected else "Down"),
    ]


def _build_gps_rows_from_runtime(network_runtime: object | None) -> list[tuple[str, str]]:
    """Build GPS rows from the Rust-owned network snapshot."""

    snapshot = _runtime_snapshot(network_runtime)
    if snapshot is None or not getattr(snapshot, "enabled", False):
        return _disabled_gps_rows()
    if not getattr(snapshot, "gps_enabled", False):
        return _disabled_gps_rows()

    gps = getattr(snapshot, "gps", None)
    if gps is None or not getattr(gps, "has_fix", False):
        state = str(getattr(snapshot, "state", "") or "").strip()
        fix_status = "Searching"
        if state in {"off", "probing", "ready"}:
            fix_status = "Starting"
        elif state not in {
            "registering",
            "registered",
            "ppp_starting",
            "online",
            "ppp_stopping",
            "recovering",
            "degraded",
        }:
            fix_status = "Unavailable"
        return [
            ("Fix", fix_status),
            ("Lat", "--"),
            ("Lng", "--"),
            ("Alt", "--"),
            ("Speed", "--"),
        ]

    return [
        ("Fix", "Yes"),
        ("Lat", f"{float(getattr(gps, 'lat', 0.0)):.6f}"),
        ("Lng", f"{float(getattr(gps, 'lng', 0.0)):.6f}"),
        ("Alt", f"{float(getattr(gps, 'altitude', 0.0)):.1f}m"),
        ("Speed", f"{float(getattr(gps, 'speed', 0.0)):.1f}km/h"),
    ]


def build_power_screen_state_provider(
    *,
    power_manager: "PowerManager | None" = None,
    network_runtime: object | None = None,
    status_provider: Callable[[], dict[str, object]] | None = None,
    playback_device_options_provider: Callable[[], list[str]] | None = None,
    capture_device_options_provider: Callable[[], list[str]] | None = None,
) -> Callable[[], PowerScreenState]:
    """Build a prepared-state provider for the Setup screen."""

    def provider() -> PowerScreenState:
        power_snapshot = power_manager.get_snapshot() if power_manager is not None else None
        try:
            status = dict(status_provider() if status_provider is not None else {})
        except Exception:
            status = {}

        network_snapshot = _runtime_snapshot(network_runtime)
        return PowerScreenState(
            snapshot=power_snapshot,
            status=status,
            network_enabled=bool(
                network_snapshot is not None and getattr(network_snapshot, "enabled", False)
            ),
            network_rows=tuple(_build_network_rows_from_runtime(network_runtime)),
            gps_rows=tuple(_build_gps_rows_from_runtime(network_runtime)),
            playback_devices=tuple(
                playback_device_options_provider() if playback_device_options_provider is not None else []
            ),
            capture_devices=tuple(
                capture_device_options_provider() if capture_device_options_provider is not None else []
            ),
        )

    return provider


def build_power_screen_actions(
    *,
    network_runtime: object | None = None,
    refresh_voice_device_options_action: Callable[[], None] | None = None,
    persist_speaker_device_action: Callable[[str | None], bool] | None = None,
    persist_capture_device_action: Callable[[str | None], bool] | None = None,
    volume_up_action: Callable[[int], int | None] | None = None,
    volume_down_action: Callable[[int], int | None] | None = None,
    mute_action: Callable[[], bool] | None = None,
    unmute_action: Callable[[], bool] | None = None,
) -> PowerScreenActions:
    """Build the focused actions for the Setup screen."""

    def refresh_gps() -> bool:
        snapshot = _runtime_snapshot(network_runtime)
        if snapshot is None or not getattr(snapshot, "enabled", False):
            return False
        if not getattr(snapshot, "gps_enabled", False):
            return False

        query_gps = getattr(network_runtime, "query_gps", None)
        if not callable(query_gps):
            return False
        return bool(query_gps())

    return PowerScreenActions(
        refresh_voice_devices=refresh_voice_device_options_action,
        refresh_gps=refresh_gps,
        persist_speaker_device=persist_speaker_device_action,
        persist_capture_device=persist_capture_device_action,
        volume_up=volume_up_action,
        volume_down=volume_down_action,
        mute=mute_action,
        unmute=unmute_action,
    )
