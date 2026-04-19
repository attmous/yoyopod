"""Reusable gallery fakes and demo fixtures."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _DemoContact:
    """Minimal contact shape used by the Whisplay gallery."""

    name: str
    sip_address: str
    favorite: bool = False
    notes: str = ""

    @property
    def display_name(self) -> str:
        return self.notes or self.name


@dataclass(frozen=True, slots=True)
class _DemoPlaylistSummary:
    """Minimal playlist list item for the gallery."""

    name: str
    uri: str
    track_count: int = 0


@dataclass(frozen=True, slots=True)
class _DemoVoiceNote:
    """Minimal latest-voice-note summary."""

    local_file_path: str


@dataclass(slots=True)
class _DemoVoiceNoteDraft:
    """Minimal active draft consumed by VoiceNoteScreen."""

    recipient_address: str
    recipient_name: str
    file_path: str
    duration_ms: int
    send_state: str
    status_text: str = ""
    message_id: str = ""


class _FakePeopleDirectory:
    """Small people-directory double for Talk screens."""

    def __init__(self, contacts: list[_DemoContact]) -> None:
        self._contacts = list(contacts)

    def get_contacts(self) -> list[_DemoContact]:
        return list(self._contacts)


class _FakeMusicService:
    """Minimal local-music service used for deterministic captures."""

    def __init__(
        self,
        *,
        playlists: list[_DemoPlaylistSummary],
        recents: list[object],
    ) -> None:
        self.is_available = True
        self._playlists = list(playlists)
        self._recents = list(recents)

    def list_playlists(self, *, fetch_track_counts: bool = False) -> list[_DemoPlaylistSummary]:
        return list(self._playlists)

    def list_recent_tracks(self) -> list[object]:
        return list(self._recents)

    def load_playlist(self, _uri: str) -> bool:
        return True

    def play_recent_track(self, _uri: str) -> bool:
        return True


class _FakeCallHistoryStore:
    """Minimal call-history store for the recents screen."""

    def __init__(self, entries: list[object]) -> None:
        self._entries = list(entries)

    def list_recent(self) -> list[object]:
        return list(self._entries)

    def mark_all_seen(self) -> None:
        for entry in self._entries:
            entry.seen = True  # type: ignore[union-attr]

    def missed_count(self) -> int:
        return sum(1 for entry in self._entries if entry.is_unseen_missed)  # type: ignore[union-attr]

    def recent_preview(self) -> list[str]:
        return [entry.title for entry in self._entries[:3]]  # type: ignore[union-attr]


class _FakePowerManager:
    """Minimal power manager exposing one stable snapshot."""

    def __init__(self, snapshot: object) -> None:
        self._snapshot = snapshot

    def get_snapshot(self) -> object:
        return self._snapshot


class _FakeNetworkManager:
    """Minimal network manager for deterministic Setup captures."""

    def __init__(self, *, gps: object | None = None) -> None:
        from yoyopod.network.models import ModemPhase, ModemState, SignalInfo

        self.config = type("Config", (), {"enabled": True, "gps_enabled": True})()
        self._gps = gps
        self._state = ModemState(
            phase=ModemPhase.REGISTERED,
            signal=SignalInfo(csq=20),
            carrier="Telekom.de",
            network_type="4G",
            sim_ready=True,
            gps=gps,
        )

    @property
    def modem_state(self) -> object:
        return self._state

    def query_gps(self) -> object | None:
        self._state.gps = self._gps
        return self._gps


class _FakeVoipManager:
    """Minimal VoIP facade used by Talk and call-state captures."""

    def __init__(
        self,
        *,
        active_voice_note: _DemoVoiceNoteDraft | None = None,
        latest_notes: dict[str, _DemoVoiceNote] | None = None,
        caller_info: dict[str, str] | None = None,
        duration_seconds: int = 0,
        muted: bool = False,
    ) -> None:
        self._status = {
            "sip_identity": "sip:kid@example.com",
            "running": True,
            "registered": True,
            "registration_state": "ok",
            "call_state": "idle",
        }
        self._latest_notes = dict(latest_notes or {})
        self.active_voice_note = active_voice_note
        self._caller_info = dict(caller_info or {})
        self._duration_seconds = duration_seconds
        self.is_muted = muted

    def get_status(self) -> dict[str, object]:
        return dict(self._status)

    def latest_voice_note_for_contact(self, sip_address: str) -> _DemoVoiceNote | None:
        return self._latest_notes.get(sip_address)

    def play_latest_voice_note(self, _sip_address: str) -> bool:
        return True

    def mark_voice_notes_seen(self, _sip_address: str) -> None:
        return None

    def make_call(self, _sip_address: str, *, contact_name: str = "") -> bool:
        self._caller_info = {
            "display_name": contact_name or "Friend",
            "address": _sip_address,
        }
        self._status["call_state"] = "outgoing"
        return True

    def answer_call(self) -> bool:
        self._status["call_state"] = "active"
        return True

    def reject_call(self) -> bool:
        self._status["call_state"] = "idle"
        return True

    def hangup(self) -> bool:
        self._status["call_state"] = "idle"
        return True

    def toggle_mute(self) -> None:
        self.is_muted = not self.is_muted

    def get_caller_info(self) -> dict[str, str]:
        return dict(self._caller_info)

    def get_call_duration(self) -> int:
        return self._duration_seconds

    def play_voice_note(self, _file_path: str) -> bool:
        return True

    def start_voice_note_recording(self, recipient_address: str, recipient_name: str = "") -> bool:
        self.active_voice_note = _DemoVoiceNoteDraft(
            recipient_address=recipient_address,
            recipient_name=recipient_name,
            file_path="data/voice_notes/demo.wav",
            duration_ms=0,
            send_state="recording",
            status_text="Recording...",
        )
        return True

    def stop_voice_note_recording(self) -> _DemoVoiceNoteDraft | None:
        if self.active_voice_note is None:
            return None
        self.active_voice_note.duration_ms = 4200
        self.active_voice_note.send_state = "review"
        self.active_voice_note.status_text = "Ready to send"
        return self.active_voice_note

    def cancel_voice_note_recording(self) -> bool:
        self.active_voice_note = None
        return True

    def discard_active_voice_note(self) -> None:
        self.active_voice_note = None

    def send_active_voice_note(self) -> bool:
        if self.active_voice_note is None:
            return False
        self.active_voice_note.send_state = "sending"
        self.active_voice_note.status_text = "Sending..."
        self.active_voice_note.message_id = "demo-note"
        return True

    def get_active_voice_note(self) -> _DemoVoiceNoteDraft | None:
        return self.active_voice_note
