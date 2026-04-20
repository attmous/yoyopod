"""Compatibility shim for callers importing ``yoyopod.voice.service``."""

from __future__ import annotations

from yoyopod.voice.manager import VoiceManager

VoiceService = VoiceManager

__all__ = ["VoiceService", "VoiceManager"]
