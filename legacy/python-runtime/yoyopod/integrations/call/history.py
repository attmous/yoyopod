"""App-facing call history row model for Rust-owned Talk history."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

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


__all__ = [
    "CallDirection",
    "CallHistoryEntry",
    "CallOutcome",
]
