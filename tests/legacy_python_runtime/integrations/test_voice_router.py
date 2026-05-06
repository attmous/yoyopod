"""Tests for command-first YoYo voice routing."""

from __future__ import annotations

from pathlib import Path

import yaml

from yoyopod.integrations.voice.dictionary import VoiceCommandDictionary
from yoyopod.integrations.voice.dictionary import load_voice_command_dictionary
from yoyopod.integrations.voice.router import (
    VoiceRouteKind,
    VoiceRouter,
)


def test_router_strips_activation_prefix_and_routes_command() -> None:
    router = VoiceRouter(
        dictionary=VoiceCommandDictionary.from_builtins(),
        activation_prefixes=("hey yoyo", "yoyo"),
        ask_fallback_enabled=True,
    )

    decision = router.route("hey yoyo call mama")

    assert decision.kind is VoiceRouteKind.COMMAND
    assert decision.normalized_text == "call mama"
    assert decision.command is not None
    assert decision.command.contact_name == "mama"
    assert decision.reason == "command_match"


def test_router_falls_back_to_ask_for_non_command() -> None:
    router = VoiceRouter(
        dictionary=VoiceCommandDictionary.from_builtins(),
        activation_prefixes=("hey yoyo", "yoyo"),
        ask_fallback_enabled=True,
    )

    decision = router.route("yoyo why is the sky blue")

    assert decision.kind is VoiceRouteKind.ASK_FALLBACK
    assert decision.normalized_text == "why is the sky blue"
    assert decision.command is None
    assert decision.reason == "ask_fallback"


def test_router_returns_local_help_when_fallback_disabled() -> None:
    router = VoiceRouter(
        dictionary=VoiceCommandDictionary.from_builtins(),
        activation_prefixes=("hey yoyo", "yoyo"),
        ask_fallback_enabled=False,
    )

    decision = router.route("tell me a story")

    assert decision.kind is VoiceRouteKind.LOCAL_HELP
    assert decision.normalized_text == "tell me a story"
    assert decision.reason == "no_command_no_fallback"


def test_router_routes_safe_dictionary_action_before_ask_fallback(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.yaml"
    commands_file.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "actions": {
                    "open_talk": {
                        "aliases": ["open talk"],
                        "route": "open_talk",
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    router = VoiceRouter(
        dictionary=load_voice_command_dictionary(commands_file),
        activation_prefixes=("hey yoyo", "yoyo"),
        ask_fallback_enabled=True,
    )

    decision = router.route("hey yoyo open talk")

    assert decision.kind is VoiceRouteKind.ACTION
    assert decision.normalized_text == "open talk"
    assert decision.route_name == "open_talk"
    assert decision.reason == "action_match"
