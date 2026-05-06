"""Focused tests for the Talk call-history row model."""

from __future__ import annotations

from yoyopod.integrations.call import CallHistoryEntry


def test_call_history_entry_formats_missed_and_completed_rows() -> None:
    """Python keeps only the app-facing row DTO; Rust owns persistence."""

    missed = CallHistoryEntry.create(
        direction="incoming",
        display_name="Mama",
        sip_address="sip:mama@example.com",
        outcome="missed",
    )
    completed = CallHistoryEntry.create(
        direction="outgoing",
        display_name="Dad",
        sip_address="sip:dad@example.com",
        outcome="completed",
        duration_seconds=72,
    )

    assert missed.is_unseen_missed is True
    assert missed.title == "Mama"
    assert missed.subtitle == "Missed call"
    assert completed.is_unseen_missed is False
    assert completed.subtitle == "Call 1:12"
