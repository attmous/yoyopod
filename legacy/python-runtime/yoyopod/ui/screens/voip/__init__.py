"""VoIP screens for YoYoPod."""

from __future__ import annotations

from yoyopod.ui._lazy_imports import exported_dir, load_attr

_EXPORTS = {
    "CallScreen": ("yoyopod.ui.screens.voip.quick_call", "CallScreen"),
    "CallHistoryScreen": (
        "yoyopod.ui.screens.voip.call_history",
        "CallHistoryScreen",
    ),
    "IncomingCallScreen": (
        "yoyopod.ui.screens.voip.incoming_call",
        "IncomingCallScreen",
    ),
    "OutgoingCallScreen": (
        "yoyopod.ui.screens.voip.outgoing_call",
        "OutgoingCallScreen",
    ),
    "InCallScreen": ("yoyopod.ui.screens.voip.in_call", "InCallScreen"),
    "ContactListScreen": (
        "yoyopod.ui.screens.voip.contact_list",
        "ContactListScreen",
    ),
    "TalkContactScreen": (
        "yoyopod.ui.screens.voip.talk_contact",
        "TalkContactScreen",
    ),
    "VoiceNoteScreen": ("yoyopod.ui.screens.voip.voice_note", "VoiceNoteScreen"),
}

__all__ = [
    'CallScreen',
    'CallHistoryScreen',
    'IncomingCallScreen',
    'OutgoingCallScreen',
    'InCallScreen',
    'ContactListScreen',
    'TalkContactScreen',
    'VoiceNoteScreen',
]


def __getattr__(name: str) -> object:
    return load_attr(_EXPORTS, __name__, name)


def __dir__() -> list[str]:
    return exported_dir(globals(), _EXPORTS)
