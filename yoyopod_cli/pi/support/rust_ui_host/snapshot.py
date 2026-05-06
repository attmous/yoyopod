"""Runtime snapshot payloads sent from Python to the Rust UI host."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from typing import Any


@dataclass(frozen=True, slots=True)
class RustUiListItem:
    id: str
    title: str
    subtitle: str = ""
    icon_key: str = ""

    def to_payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "subtitle": self.subtitle,
            "icon_key": self.icon_key,
        }


@dataclass(frozen=True, slots=True)
class RustUiHubCard:
    key: str
    title: str
    subtitle: str = ""
    accent: int = 0x00FF88

    def to_payload(self) -> dict[str, object]:
        return {
            "key": self.key,
            "title": self.title,
            "subtitle": self.subtitle,
            "accent": self.accent,
        }


@dataclass(frozen=True, slots=True)
class RustUiRuntimeSnapshot:
    app_state: str = "hub"
    hub_cards: list[RustUiHubCard] = field(default_factory=list)
    music_title: str = "Nothing Playing"
    music_artist: str = ""
    music_playing: bool = False
    music_paused: bool = False
    music_progress_permille: int = 0
    playlists: list[RustUiListItem] = field(default_factory=list)
    recent_tracks: list[RustUiListItem] = field(default_factory=list)
    call_state: str = "idle"
    call_peer_name: str = ""
    call_peer_address: str = ""
    call_duration_text: str = ""
    call_muted: bool = False
    contacts: list[RustUiListItem] = field(default_factory=list)
    call_history: list[RustUiListItem] = field(default_factory=list)
    voice_phase: str = "idle"
    voice_headline: str = "Ask"
    voice_body: str = "Ask me anything..."
    voice_capture_in_flight: bool = False
    voice_ptt_active: bool = False
    battery_percent: int = 100
    charging: bool = False
    power_available: bool = True
    power_rows: list[str] = field(default_factory=list)
    network_enabled: bool = False
    network_connected: bool = False
    network_signal_strength: int = 0
    network_gps_has_fix: bool = False
    overlay_loading: bool = False
    overlay_error: str = ""
    overlay_message: str = ""

    @classmethod
    def from_app(cls, app: Any) -> "RustUiRuntimeSnapshot":
        context = getattr(app, "context", None)
        app_state_runtime = getattr(app, "app_state_runtime", None)
        app_state = _call_or_default(app_state_runtime, "get_state_name", "hub")

        track = context.get_current_track() if context is not None else None
        playback = getattr(getattr(context, "media", None), "playback", None)
        power = getattr(context, "power", None)
        network = getattr(context, "network", None)
        voip = getattr(context, "voip", None)
        voice = getattr(context, "voice", None)
        interaction = getattr(voice, "interaction", None)

        music_title = getattr(track, "name", "") or "Nothing Playing"
        music_artist = (
            track.get_artist_string()
            if track is not None and callable(getattr(track, "get_artist_string", None))
            else ""
        )
        progress_permille = (
            int(round(float(context.get_playback_progress()) * 1000)) if context is not None else 0
        )
        call_peer_name, call_peer_address = _call_peer_from_app(app)

        return cls(
            app_state=str(app_state or "hub"),
            music_title=music_title,
            music_artist=music_artist,
            music_playing=bool(getattr(playback, "is_playing", False)),
            music_paused=bool(getattr(playback, "is_paused", False)),
            music_progress_permille=_clamp_int(progress_permille, 0, 1000),
            playlists=_playlist_items(context),
            recent_tracks=_recent_track_items(app),
            contacts=_contact_items(getattr(app, "people_directory", None)),
            call_history=_call_history_items(getattr(app, "voip_manager", None)),
            call_state=_call_state_from_app(app),
            call_peer_name=call_peer_name,
            call_peer_address=call_peer_address,
            call_duration_text=_call_duration_text(app),
            call_muted=_call_muted(app),
            voice_phase=str(getattr(interaction, "phase", "idle")),
            voice_headline=str(getattr(interaction, "headline", "Ask")),
            voice_body=str(getattr(interaction, "body", "Ask me anything...")),
            voice_capture_in_flight=bool(getattr(interaction, "capture_in_flight", False)),
            voice_ptt_active=bool(getattr(interaction, "ptt_active", False)),
            battery_percent=_clamp_int(getattr(power, "battery_percent", 100), 0, 100),
            charging=bool(getattr(power, "battery_charging", False)),
            power_available=bool(getattr(power, "available", True)),
            power_rows=_power_rows(power, network, voip),
            network_enabled=bool(getattr(network, "enabled", False)),
            network_connected=bool(getattr(network, "connected", False)),
            network_signal_strength=_clamp_int(getattr(network, "signal_strength", 0), 0, 4),
            network_gps_has_fix=bool(getattr(network, "gps_has_fix", False)),
        ).with_default_hub_cards()

    def with_default_hub_cards(self) -> "RustUiRuntimeSnapshot":
        if self.hub_cards:
            return self
        return replace(
            self,
            hub_cards=[
                RustUiHubCard(
                    key="listen",
                    title="Listen",
                    subtitle=f"Playing {self.music_title}" if self.music_playing else "Music",
                    accent=0x00FF88,
                ),
                RustUiHubCard(
                    key="talk",
                    title="Talk",
                    subtitle=_talk_subtitle(self),
                    accent=0x00D4FF,
                ),
                RustUiHubCard(
                    key="ask",
                    title="Ask",
                    subtitle=self.voice_phase.title(),
                    accent=0x9F7AEA,
                ),
                RustUiHubCard(
                    key="setup",
                    title="Setup",
                    subtitle=f"{self.battery_percent}%",
                    accent=0xF6AD55,
                ),
            ],
        )

    def to_payload(self) -> dict[str, object]:
        snapshot = self.with_default_hub_cards()
        return {
            "app_state": snapshot.app_state,
            "hub": {"cards": [card.to_payload() for card in snapshot.hub_cards]},
            "music": {
                "playing": snapshot.music_playing,
                "paused": snapshot.music_paused,
                "title": snapshot.music_title,
                "artist": snapshot.music_artist,
                "progress_permille": snapshot.music_progress_permille,
                "playlists": [item.to_payload() for item in snapshot.playlists],
                "recent_tracks": [item.to_payload() for item in snapshot.recent_tracks],
            },
            "call": {
                "state": snapshot.call_state,
                "peer_name": snapshot.call_peer_name,
                "peer_address": snapshot.call_peer_address,
                "duration_text": snapshot.call_duration_text,
                "muted": snapshot.call_muted,
                "contacts": [item.to_payload() for item in snapshot.contacts],
                "history": [item.to_payload() for item in snapshot.call_history],
            },
            "voice": {
                "phase": snapshot.voice_phase,
                "headline": snapshot.voice_headline,
                "body": snapshot.voice_body,
                "capture_in_flight": snapshot.voice_capture_in_flight,
                "ptt_active": snapshot.voice_ptt_active,
            },
            "power": {
                "battery_percent": snapshot.battery_percent,
                "charging": snapshot.charging,
                "power_available": snapshot.power_available,
                "rows": list(snapshot.power_rows),
            },
            "network": {
                "enabled": snapshot.network_enabled,
                "connected": snapshot.network_connected,
                "signal_strength": snapshot.network_signal_strength,
                "gps_has_fix": snapshot.network_gps_has_fix,
            },
            "overlay": {
                "loading": snapshot.overlay_loading,
                "error": snapshot.overlay_error,
                "message": snapshot.overlay_message,
            },
        }

    def as_flat_dict(self) -> dict[str, object]:
        """Return dataclass fields without nested payload conversion."""

        return {field_info.name: getattr(self, field_info.name) for field_info in fields(self)}


def _playlist_items(context: Any) -> list[RustUiListItem]:
    media = getattr(context, "media", None)
    playlists = getattr(media, "playlists", {}) if media is not None else {}
    result: list[RustUiListItem] = []
    for key, playlist in dict(playlists).items():
        title = str(getattr(playlist, "name", key))
        source_uri = getattr(playlist, "source_uri", None)
        track_count = int(getattr(playlist, "track_count", 0))
        result.append(
            RustUiListItem(
                id=str(source_uri or key),
                title=title,
                subtitle=f"{track_count} tracks" if track_count else "",
                icon_key="playlist",
            )
        )
    return result


def _contact_items(people_directory: Any) -> list[RustUiListItem]:
    if people_directory is None:
        return []
    get_contacts = getattr(people_directory, "get_callable_contacts", None)
    if not callable(get_contacts):
        return []

    result: list[RustUiListItem] = []
    for contact in get_contacts():
        target = _contact_target(contact)
        if not target:
            continue
        result.append(
            RustUiListItem(
                id=target,
                title=str(getattr(contact, "display_name", "") or getattr(contact, "name", "")),
                subtitle=target,
                icon_key="person",
            )
        )
    return result


def _contact_target(contact: Any) -> str:
    preferred = getattr(contact, "preferred_call_target", None)
    if callable(preferred):
        route, address = preferred(gsm_enabled=False)
        if route and address:
            return str(address)
    return str(getattr(contact, "sip_address", "")).strip()


def _recent_track_items(app: Any) -> list[RustUiListItem]:
    music_service = _resolve_music_service(app)
    list_recent_tracks = getattr(music_service, "list_recent_tracks", None)
    if not callable(list_recent_tracks):
        return []

    result: list[RustUiListItem] = []
    for track in list_recent_tracks():
        uri = str(getattr(track, "uri", "")).strip()
        if not uri:
            continue
        result.append(
            RustUiListItem(
                id=uri,
                title=str(getattr(track, "title", "") or "Unknown Track"),
                subtitle=str(getattr(track, "subtitle", "") or "Played recently"),
                icon_key="track",
            )
        )
    return result


def _resolve_music_service(app: Any) -> Any:
    getter = getattr(app, "get_music_library", None)
    if callable(getter):
        try:
            return getter()
        except Exception:
            return None
    return getattr(app, "local_music_service", None)


def _call_history_items(voip_manager: Any) -> list[RustUiListItem]:
    list_recent = getattr(voip_manager, "call_history_recent_entries", None)
    if not callable(list_recent):
        return []

    result: list[RustUiListItem] = []
    for entry in list_recent():
        target = str(getattr(entry, "sip_address", "")).strip()
        if not target:
            continue
        result.append(
            RustUiListItem(
                id=target,
                title=str(getattr(entry, "title", "") or target),
                subtitle=str(getattr(entry, "subtitle", "") or "Recent call"),
                icon_key=(
                    "missed_call" if str(getattr(entry, "outcome", "")) == "missed" else "call"
                ),
            )
        )
    return result


def _call_state_from_app(app: Any) -> str:
    call_fsm = getattr(app, "call_fsm", None)
    state = getattr(call_fsm, "state", None)
    value = getattr(state, "value", state)
    return str(value or "idle")


def _call_peer_from_app(app: Any) -> tuple[str, str]:
    manager = getattr(app, "voip_manager", None)
    get_caller_info = getattr(manager, "get_caller_info", None)
    if callable(get_caller_info):
        info = get_caller_info() or {}
        return str(info.get("display_name") or ""), str(info.get("address") or "")
    return "", ""


def _call_duration_text(app: Any) -> str:
    manager = getattr(app, "voip_manager", None)
    get_call_duration = getattr(manager, "get_call_duration", None)
    if not callable(get_call_duration):
        return ""
    seconds = max(0, int(get_call_duration()))
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}:{seconds:02d}"


def _call_muted(app: Any) -> bool:
    manager = getattr(app, "voip_manager", None)
    return bool(getattr(manager, "is_muted", False))


def _power_rows(power: Any, network: Any, voip: Any) -> list[str]:
    return [
        f"Battery {_clamp_int(getattr(power, 'battery_percent', 100), 0, 100)}%",
        "Charging" if bool(getattr(power, "battery_charging", False)) else "On battery",
        "Network connected" if bool(getattr(network, "connected", False)) else "Network offline",
        "VoIP ready" if bool(getattr(voip, "ready", False)) else "VoIP offline",
    ]


def _talk_subtitle(snapshot: RustUiRuntimeSnapshot) -> str:
    if snapshot.call_state != "idle":
        return snapshot.call_state.replace("_", " ").title()
    return "Ready" if snapshot.contacts else "No contacts"


def _call_or_default(obj: Any, method_name: str, default: str) -> str:
    method = getattr(obj, method_name, None)
    if callable(method):
        return str(method())
    return default


def _clamp_int(value: object, lower: int, upper: int) -> int:
    try:
        integer = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        integer = lower
    return max(lower, min(upper, integer))
