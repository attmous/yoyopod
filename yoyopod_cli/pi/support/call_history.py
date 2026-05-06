"""Call history row model used by CLI-owned VoIP diagnostics."""

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
    """One app-facing Talk call history entry."""

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
    def title(self) -> str:
        """Return the main list title for this entry."""

        return self.display_name or self.sip_address or "Unknown"

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
            duration_seconds=_duration_seconds_from_value(data.get("duration_seconds")),
            seen=bool(data.get("seen", False)),
            id=str(data.get("id", uuid4().hex)),
        )


def _duration_seconds_from_value(value: object) -> int:
    if value in (None, ""):
        return 0
    if not isinstance(value, (int, float, str, bytes, bytearray)):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


__all__ = ["CallDirection", "CallHistoryEntry", "CallOutcome"]
