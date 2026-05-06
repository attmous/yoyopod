"""Small call-action interfaces exposed to Talk screens."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class CallActions:
    """Focused call actions that screens can trigger without owning VoIP managers."""

    answer_call: Callable[[], bool] | None = None
    reject_call: Callable[[], bool] | None = None
    hangup_call: Callable[[], bool] | None = None
    make_call: Callable[[str, str | None], bool] | None = None

