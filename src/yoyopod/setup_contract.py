"""Shared setup and boot-time config contract for YoyoPod."""

from __future__ import annotations

from pathlib import Path

RUNTIME_REQUIRED_CONFIG_FILES: tuple[Path, ...] = (
    Path("config/app/core.yaml"),
    Path("config/audio/music.yaml"),
    Path("config/device/hardware.yaml"),
    Path("config/power/backend.yaml"),
    Path("config/network/cellular.yaml"),
    Path("config/voice/assistant.yaml"),
    Path("config/communication/calling.yaml"),
    Path("config/communication/messaging.yaml"),
    Path("config/people/directory.yaml"),
)

SETUP_TRACKED_CONFIG_FILES: tuple[Path, ...] = (
    *RUNTIME_REQUIRED_CONFIG_FILES,
    Path("config/communication/calling.secrets.example.yaml"),
    Path("config/communication/integrations/liblinphone_factory.conf"),
    Path("config/people/contacts.seed.yaml"),
    Path("deploy/pi-deploy.yaml"),
)
