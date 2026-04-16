"""Focused tests for the Talk call-history persistence layer."""

from __future__ import annotations

from pathlib import Path

from yoyopod.communication.calling.history import CallHistoryEntry, CallHistoryStore


def test_call_history_store_persists_and_restores_entries(tmp_path: Path) -> None:
    """Call history should survive a save/load round-trip."""

    history_file = tmp_path / "call_history.json"
    store = CallHistoryStore(history_file)
    store.add_entry(
        CallHistoryEntry.create(
            direction="incoming",
            display_name="Hagar",
            sip_address="sip:hagar@example.com",
            outcome="missed",
        )
    )

    reloaded = CallHistoryStore(history_file)
    recent = reloaded.list_recent()

    assert len(recent) == 1
    assert recent[0].display_name == "Hagar"
    assert recent[0].outcome == "missed"
    assert reloaded.missed_count() == 1


def test_call_history_store_marks_missed_calls_seen(tmp_path: Path) -> None:
    """Opening recents should clear the unseen missed-call badge count."""

    history_file = tmp_path / "call_history.json"
    store = CallHistoryStore(history_file)
    store.add_entry(
        CallHistoryEntry.create(
            direction="incoming",
            display_name="Mama",
            sip_address="sip:mama@example.com",
            outcome="missed",
        )
    )

    assert store.missed_count() == 1
    store.mark_all_seen()

    assert store.missed_count() == 0
    assert store.list_recent()[0].seen is True
