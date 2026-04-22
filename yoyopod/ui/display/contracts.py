"""Display-layer runtime contracts for supported hardware modes."""

from __future__ import annotations


class WhisplayProductionRenderContractError(RuntimeError):
    """Raised when a Whisplay production run would fall back unsafely."""


def build_whisplay_production_contract_message(reason: str) -> str:
    """Return one consistent startup failure message for Whisplay production runs."""

    normalized_reason = reason.strip().rstrip(".")
    return (
        f"{normalized_reason}. Refusing to continue because Whisplay production runs require "
        "the LVGL renderer on real hardware and do not allow PIL or simulation fallback. "
        "Use `python yoyopod.py --simulate` for local debug fallback, or run "
        "`yoyopod build lvgl` on the target to restore the supported render path."
    )
