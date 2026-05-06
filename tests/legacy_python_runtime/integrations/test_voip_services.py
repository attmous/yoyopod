"""Focused tests for the Rust-owned VoIP production seam."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from yoyopod.integrations.call.models import VoIPConfig


def build_config(tmp_path: Path) -> VoIPConfig:
    """Create a test VoIP configuration backed by temporary runtime paths."""

    return VoIPConfig(
        sip_server="sip.example.com",
        sip_username="alice",
        sip_password_ha1="hash",
        sip_identity="sip:alice@sip.example.com",
        file_transfer_server_url="https://transfer.example.com",
        message_store_dir=str(tmp_path / "messages"),
        voice_note_store_dir=str(tmp_path / "voice_notes"),
    )


def test_voip_config_requires_server_and_identity_for_backend_start(tmp_path: Path) -> None:
    """Backend startup should only proceed when the canonical SIP minimum is configured."""

    config = build_config(tmp_path)

    assert config.is_backend_start_configured() is True

    config.sip_identity = ""
    assert config.is_backend_start_configured() is False

    config.sip_identity = "sip:alice@sip.example.com"
    config.sip_server = ""
    assert config.is_backend_start_configured() is False


@pytest.mark.parametrize(
    "name",
    [
        "MessagingService",
        "VoIPMessageStore",
        "VoiceNoteService",
        "ActiveCallSession",
        "CallHistoryStore",
        "CallSessionTracker",
    ],
)
def test_legacy_python_voip_services_are_not_public_call_exports(name: str) -> None:
    """Production callers must not reach Python-owned VoIP domain services."""

    call_module = importlib.import_module("yoyopod.integrations.call")

    assert name not in getattr(call_module, "__all__", ())
    with pytest.raises(AttributeError):
        getattr(call_module, name)


@pytest.mark.parametrize(
    "name",
    [
        "CallStateChangedEvent",
        "IncomingCallEvent",
    ],
)
def test_legacy_python_call_events_are_not_public_call_events(name: str) -> None:
    """Live call state should be projected only from Rust runtime snapshots."""

    events_module = importlib.import_module("yoyopod.integrations.call.events")

    assert name not in getattr(events_module, "__all__", ())
    with pytest.raises(AttributeError):
        getattr(events_module, name)


@pytest.mark.parametrize(
    "name",
    [
        "on_call_state_change",
        "on_incoming_call",
    ],
)
def test_voip_manager_does_not_expose_legacy_call_callbacks(name: str) -> None:
    """The Python supervisor should not expose live-call callback ownership."""

    manager_module = importlib.import_module("yoyopod.integrations.call.manager")

    assert not hasattr(manager_module.VoIPManager, name)


@pytest.mark.parametrize(
    "module_name",
    [
        "yoyopod.integrations.call.messaging",
        "yoyopod.integrations.call.message_store",
        "yoyopod.integrations.call.voice_notes",
        "yoyopod.integrations.call.lifecycle",
    ],
)
def test_legacy_python_voip_service_modules_are_quarantined(module_name: str) -> None:
    """Legacy Python service modules should not remain importable in production code."""

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module_name)
