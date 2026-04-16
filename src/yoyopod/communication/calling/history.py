"""Persistent call history for the Talk flow."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from loguru import logger

CallDirection = Literal["incoming", "outgoing"]
CallOutcome = Literal["missed", "completed", "cancelled", "rejected", "failed"]


def _utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO8601 string."""

    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class CallHistoryEntry:
    """One persisted Talk call history entry."""

    direction: CallDirection
    display_name: str
    sip_address: str
    outcome: CallOutcome
    started_at: str
    ended_at: str
    duration_seconds: int = 0
    seen: bool = False
    id: str = field(default_factory=lambda: uuid4().hex)

    @property
    def is_unseen_missed(self) -> bool:
        """Return True when this entry is a missed call the child has not opened yet."""

        return self.outcome == "missed" and not self.seen

    @property
    def title(self) -> str:
        """Return the main list title for this entry."""

        return self.display_name or self.sip_address or "Unknown"

    @property
    def subtitle(self) -> str:
        """Return a compact human-readable outcome summary."""

        if self.outcome == "missed":
            return "Missed call"
        if self.outcome == "completed":
            if self.duration_seconds > 0:
                minutes, seconds = divmod(max(0, self.duration_seconds), 60)
                return f"Call {minutes}:{seconds:02d}"
            return "Call done"
        if self.outcome == "rejected":
            return "Rejected"
        if self.outcome == "failed":
            return "Failed"
        return "Cancelled"

    @classmethod
    def create(
        cls,
        *,
        direction: CallDirection,
        display_name: str,
        sip_address: str,
        outcome: CallOutcome,
        duration_seconds: int = 0,
    ) -> "CallHistoryEntry":
        """Create a new entry using the current time for start/end."""

        now = _utc_now_iso()
        return cls(
            direction=direction,
            display_name=display_name,
            sip_address=sip_address,
            outcome=outcome,
            started_at=now,
            ended_at=now,
            duration_seconds=max(0, int(duration_seconds)),
            seen=outcome != "missed",
        )

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "CallHistoryEntry":
        """Build an entry from persisted JSON data."""

        return cls(
            direction=str(data.get("direction", "incoming")),  # type: ignore[arg-type]
            display_name=str(data.get("display_name", "")),
            sip_address=str(data.get("sip_address", "")),
            outcome=str(data.get("outcome", "failed")),  # type: ignore[arg-type]
            started_at=str(data.get("started_at", _utc_now_iso())),
            ended_at=str(data.get("ended_at", _utc_now_iso())),
            duration_seconds=max(0, int(data.get("duration_seconds", 0) or 0)),
            seen=bool(data.get("seen", False)),
            id=str(data.get("id", uuid4().hex)),
        )


class CallHistoryStore:
    """Persist and query Talk call history for the kid-facing UI."""

    def __init__(self, history_file: str | Path, max_entries: int = 50) -> None:
        self.history_file = Path(history_file)
        self.max_entries = max(1, int(max_entries))
        self._entries: list[CallHistoryEntry] = []
        self.load()

    def load(self) -> None:
        """Load history from disk if present."""

        if not self.history_file.exists():
            self._entries = []
            return

        try:
            with open(self.history_file, "r", encoding="utf-8") as handle:
                payload = json.load(handle) or {}
            items = payload.get("entries", [])
            self._entries = [CallHistoryEntry.from_dict(item) for item in items]
            self._entries = self._entries[: self.max_entries]
        except Exception as exc:
            logger.warning(f"Failed to load call history from {self.history_file}: {exc}")
            self._entries = []

    def save(self) -> None:
        """Persist the current history state to disk."""

        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_file, "w", encoding="utf-8") as handle:
                json.dump(
                    {"entries": [asdict(entry) for entry in self._entries[: self.max_entries]]},
                    handle,
                    indent=2,
                )
        except Exception as exc:
            logger.warning(f"Failed to save call history to {self.history_file}: {exc}")

    def add_entry(self, entry: CallHistoryEntry) -> None:
        """Append a new call history entry and persist it."""

        self._entries.insert(0, entry)
        self._entries = self._entries[: self.max_entries]
        self.save()

    def list_recent(self, limit: int | None = None) -> list[CallHistoryEntry]:
        """Return recent history entries, newest first."""

        if limit is None:
            return list(self._entries)
        return list(self._entries[: max(0, limit)])

    def recent_preview(self, limit: int = 3) -> list[str]:
        """Return a short preview list suitable for the root hub and context."""

        return [entry.title for entry in self.list_recent(limit)]

    def missed_count(self) -> int:
        """Return the number of unseen missed calls."""

        return sum(1 for entry in self._entries if entry.is_unseen_missed)

    def mark_all_seen(self) -> None:
        """Mark missed calls as seen once the child opens recents/history."""

        changed = False
        for entry in self._entries:
            if entry.is_unseen_missed:
                entry.seen = True
                changed = True
        if changed:
            self.save()

