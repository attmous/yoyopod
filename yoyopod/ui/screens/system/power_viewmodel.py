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


def _build_network_rows_from_manager(network_manager: object | None) -> list[tuple[str, str]]:
    """Build the cellular network status rows from a backend-facing manager."""

    if network_manager is None or not getattr(network_manager, "config", None) or not network_manager.config.enabled:
        return [("Status", "Disabled")]

    from yoyopod.integrations.network.models import ModemPhase

    state = network_manager.modem_state
    if state.phase == ModemPhase.ONLINE:
        status_text = "Online"
    elif state.phase in (
        ModemPhase.REGISTERED,
        ModemPhase.PPP_STARTING,
        ModemPhase.PPP_STOPPING,
    ):
        status_text = "Registered"
    elif state.phase in (ModemPhase.PROBING, ModemPhase.READY, ModemPhase.REGISTERING):
        status_text = "Connecting"
    else:
        status_text = "Offline"

    return [
        ("Status", status_text),
        ("Carrier", state.carrier or "Unknown"),
        ("Type", state.network_type or "Unknown"),
        ("Signal", f"{state.signal.bars}/4" if state.signal else "Unknown"),
        ("PPP", "Up" if state.phase == ModemPhase.ONLINE else "Down"),
    ]


def _build_gps_rows_from_manager(network_manager: object | None) -> list[tuple[str, str]]:
    """Build the GPS status rows from a backend-facing manager."""

    if network_manager is None or not getattr(network_manager, "config", None) or not network_manager.config.enabled:
        return [
            ("Fix", "Disabled"),
            ("Lat", "--"),
            ("Lng", "--"),
            ("Alt", "--"),
            ("Speed", "--"),
        ]
    if not network_manager.config.gps_enabled:
        return [
            ("Fix", "Disabled"),
            ("Lat", "--"),
            ("Lng", "--"),
            ("Alt", "--"),
            ("Speed", "--"),
        ]

    from yoyopod.integrations.network.models import ModemPhase

    state = network_manager.modem_state
    if state.gps is None:
        fix_status = "Searching"
        if state.phase in (ModemPhase.OFF, ModemPhase.PROBING, ModemPhase.READY):
            fix_status = "Starting"
        elif state.phase not in (
            ModemPhase.REGISTERING,
            ModemPhase.REGISTERED,
            ModemPhase.PPP_STARTING,
            ModemPhase.PPP_STOPPING,
            ModemPhase.ONLINE,
        ):
            fix_status = "Unavailable"
        return [
            ("Fix", fix_status),
            ("Lat", "--"),
            ("Lng", "--"),
            ("Alt", "--"),
            ("Speed", "--"),
        ]

    coord = state.gps
    return [
        ("Fix", "Yes"),
        ("Lat", f"{coord.lat:.6f}"),
        ("Lng", f"{coord.lng:.6f}"),
        ("Alt", f"{coord.altitude:.1f}m"),
        ("Speed", f"{coord.speed:.1f}km/h"),
    ]


def build_power_screen_state_provider(
    *,
    power_manager: "PowerManager | None" = None,
    network_manager: object | None = None,
    status_provider: Callable[[], dict[str, object]] | None = None,
    playback_device_options_provider: Callable[[], list[str]] | None = None,
    capture_device_options_provider: Callable[[], list[str]] | None = None,
) -> Callable[[], PowerScreenState]:
    """Build a prepared-state provider for the Setup screen."""

    def provider() -> PowerScreenState:
        snapshot = power_manager.get_snapshot() if power_manager is not None else None
        try:
            status = dict(status_provider() if status_provider is not None else {})
        except Exception:
            status = {}

        return PowerScreenState(
            snapshot=snapshot,
            status=status,
            network_enabled=bool(
                network_manager is not None and getattr(network_manager.config, "enabled", False)
            ),
            network_rows=tuple(_build_network_rows_from_manager(network_manager)),
            gps_rows=tuple(_build_gps_rows_from_manager(network_manager)),
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
    network_manager: object | None = None,
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
        if network_manager is None or not getattr(network_manager.config, "enabled", False):
            return False
        if not getattr(network_manager.config, "gps_enabled", False):
            return False

        query_gps = getattr(network_manager, "query_gps", None)
        if not callable(query_gps):
            return False
        return query_gps() is not None

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
