"""Entity state store for the Phase A spine scaffold."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from yoyopod.core.bus import Bus
from yoyopod.core.events import StateChangedEvent


@dataclass(frozen=True, slots=True)
class StateValue:
    """One stored entity value."""

    value: Any
    attrs: dict[str, Any]
    last_changed_at: float


class States:
    """In-memory entity store with automatic state-changed events."""

    def __init__(self, bus: Bus, clock: Callable[[], float] | None = None) -> None:
        self._bus = bus
        self._clock = clock or time.monotonic
        self._state: dict[str, StateValue] = {}

    def set(self, entity: str, value: Any, attrs: dict[str, Any] | None = None) -> None:
        """Set one entity value and publish `StateChangedEvent` when it changes."""

        new_attrs = dict(attrs or {})
        current = self._state.get(entity)
        if current is not None and current.value == value and current.attrs == new_attrs:
            return

        changed_at = self._clock()
        next_value = StateValue(value=value, attrs=new_attrs, last_changed_at=changed_at)
        self._state[entity] = next_value
        self._bus.publish(
            StateChangedEvent(
                entity=entity,
                old=None if current is None else current.value,
                new=value,
                attrs=dict(new_attrs),
                last_changed_at=changed_at,
            )
        )

    def get(self, entity: str) -> StateValue | None:
        """Return one stored entity, or `None` when it is unset."""

        current = self._state.get(entity)
        if current is None:
            return None
        return StateValue(
            value=current.value,
            attrs=dict(current.attrs),
            last_changed_at=current.last_changed_at,
        )

    def get_value(self, entity: str, default: Any = None) -> Any:
        """Return the stored value or a caller-provided default."""

        current = self._state.get(entity)
        if current is None:
            return default
        return current.value

    def all(self) -> dict[str, StateValue]:
        """Return a snapshot of the full state store."""

        return {
            entity: StateValue(
                value=current.value,
                attrs=dict(current.attrs),
                last_changed_at=current.last_changed_at,
            )
            for entity, current in self._state.items()
        }

    def has(self, entity: str) -> bool:
        """Return whether one entity exists."""

        return entity in self._state
