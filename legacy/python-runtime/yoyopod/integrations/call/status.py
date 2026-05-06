"""Canonical helpers for deriving and publishing VoIP runtime status."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yoyopod_cli.pi.support.call_models import RegistrationState

if TYPE_CHECKING:
    from yoyopod.core import AppContext


def is_voip_configured(config_manager: object | None) -> bool:
    """Return whether the current config exposes a usable SIP identity."""

    if config_manager is None:
        return False

    get_sip_identity = getattr(config_manager, "get_sip_identity", None)
    if callable(get_sip_identity) and str(get_sip_identity()).strip():
        return True

    get_sip_username = getattr(config_manager, "get_sip_username", None)
    if callable(get_sip_username) and str(get_sip_username()).strip():
        return True

    return False


def sync_context_voip_status(
    context: "AppContext | None",
    *,
    config_manager: object | None,
    ready: bool,
    running: bool | None,
    registration_state: RegistrationState | str | None,
) -> None:
    """Update shared app context using the canonical VoIP status rules."""

    if context is None:
        return

    registration_state_value: str | None
    if isinstance(registration_state, RegistrationState):
        registration_state_value = registration_state.value
    elif registration_state is None:
        registration_state_value = None
    else:
        registration_state_value = str(registration_state)

    context.update_voip_status(
        configured=is_voip_configured(config_manager),
        ready=ready,
        running=running,
        registration_state=registration_state_value,
    )


__all__ = ["is_voip_configured", "sync_context_voip_status"]
