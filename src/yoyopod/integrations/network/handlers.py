"""State helpers for the scaffold network integration."""

from __future__ import annotations

from typing import Any


def apply_modem_status_to_state(app: Any, status: Any) -> None:
    """Mirror a modem status snapshot into the scaffold state store."""

    app.states.set(
        "network.cellular_registered",
        bool(status.registered),
        {
            "carrier": str(getattr(status, "carrier", "")),
            "network_type": str(getattr(status, "network_type", "")),
        },
    )


def apply_ppp_status_to_state(app: Any, *, up: bool, reason: str = "") -> None:
    """Mirror PPP link state into scaffold state."""

    app.states.set("network.ppp_up", bool(up), {"reason": reason} if reason else {})


def apply_signal_to_state(app: Any, *, csq: int | None, bars: int | None) -> None:
    """Mirror one signal sample into scaffold state."""

    normalized_bars = None if bars is None else max(0, int(bars))
    normalized_csq = None if csq is None else max(0, int(csq))
    app.states.set(
        "network.signal_bars",
        normalized_bars,
        {"csq": normalized_csq},
    )
