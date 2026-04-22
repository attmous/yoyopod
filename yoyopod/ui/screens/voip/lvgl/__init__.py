"""LVGL-backed VoIP screen views."""

from __future__ import annotations

from yoyopod.ui._lazy_imports import exported_dir, load_attr

_EXPORTS = {
    "LvglCallView": ("yoyopod.ui.screens.voip.lvgl.call_view", "LvglCallView"),
    "LvglCallHistoryView": (
        "yoyopod.ui.screens.voip.lvgl.call_history_view",
        "LvglCallHistoryView",
    ),
    "LvglContactListView": (
        "yoyopod.ui.screens.voip.lvgl.contact_list_view",
        "LvglContactListView",
    ),
    "LvglInCallView": (
        "yoyopod.ui.screens.voip.lvgl.in_call_view",
        "LvglInCallView",
    ),
    "LvglIncomingCallView": (
        "yoyopod.ui.screens.voip.lvgl.incoming_call_view",
        "LvglIncomingCallView",
    ),
    "LvglOutgoingCallView": (
        "yoyopod.ui.screens.voip.lvgl.outgoing_call_view",
        "LvglOutgoingCallView",
    ),
    "LvglTalkContactView": (
        "yoyopod.ui.screens.voip.lvgl.talk_contact_view",
        "LvglTalkContactView",
    ),
    "LvglVoiceNoteView": (
        "yoyopod.ui.screens.voip.lvgl.voice_note_view",
        "LvglVoiceNoteView",
    ),
}

__all__ = [
    "LvglCallView",
    "LvglCallHistoryView",
    "LvglContactListView",
    "LvglInCallView",
    "LvglIncomingCallView",
    "LvglOutgoingCallView",
    "LvglTalkContactView",
    "LvglVoiceNoteView",
]


def __getattr__(name: str) -> object:
    return load_attr(_EXPORTS, __name__, name)


def __dir__() -> list[str]:
    return exported_dir(globals(), _EXPORTS)
