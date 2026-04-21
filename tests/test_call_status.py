"""Focused tests for canonical VoIP status helpers."""

from __future__ import annotations

from yoyopod.core import AppContext
from yoyopod.integrations.call import (
    RegistrationState,
    is_voip_configured,
    sync_context_voip_status,
)


class _ConfigManagerStub:
    def __init__(self, *, sip_identity: str = "", sip_username: str = "") -> None:
        self._sip_identity = sip_identity
        self._sip_username = sip_username

    def get_sip_identity(self) -> str:
        return self._sip_identity

    def get_sip_username(self) -> str:
        return self._sip_username


def test_is_voip_configured_uses_identity_or_username() -> None:
    """VoIP configuration should require either SIP identity or SIP username."""

    assert not is_voip_configured(_ConfigManagerStub())
    assert is_voip_configured(_ConfigManagerStub(sip_identity="sip:kid@example.com"))
    assert is_voip_configured(_ConfigManagerStub(sip_username="kid@example.com"))


def test_sync_context_voip_status_uses_canonical_configuration_rules() -> None:
    """Shared status sync should populate AppContext using the canonical helper."""

    context = AppContext()

    sync_context_voip_status(
        context,
        config_manager=_ConfigManagerStub(sip_username="kid@example.com"),
        ready=True,
        running=True,
        registration_state=RegistrationState.OK,
    )

    assert context.voip.configured is True
    assert context.voip.ready is True
    assert context.voip.running is True
    assert context.voip.registration_state == RegistrationState.OK.value
