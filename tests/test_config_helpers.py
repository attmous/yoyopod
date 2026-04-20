"""Focused tests for extracted config helpers."""

from pathlib import Path

from yoyopod.config.composition import (
    deep_merge_mappings,
    resolve_config_board,
    resolve_config_layers,
)
from yoyopod.people import Contact, contacts_from_mapping, contacts_to_mapping


def test_deep_merge_mappings_recurses_without_losing_base_values() -> None:
    """Nested config overlays should override only the keys they redefine."""

    merged = deep_merge_mappings(
        {"audio": {"music_dir": "/srv/music", "default_volume": 72}},
        {"audio": {"music_dir": "/home/radxa/Music"}},
    )

    assert merged == {
        "audio": {
            "music_dir": "/home/radxa/Music",
            "default_volume": 72,
        }
    }


def test_contacts_round_trip_between_yaml_mapping_and_models() -> None:
    """Contact serialization helpers should preserve kid-facing labels and flags."""

    payload = {
        "contacts": [
            {
                "name": "Hagar",
                "sip_address": "sip:mama@example.com",
                "favorite": True,
                "notes": "Mama",
            }
        ],
        "speed_dial": {1: "sip:mama@example.com"},
    }

    contacts, speed_dial = contacts_from_mapping(payload)
    rebuilt = contacts_to_mapping(contacts, speed_dial)

    assert contacts == [
        Contact(
            name="Hagar",
            sip_address="sip:mama@example.com",
            favorite=True,
            notes="Mama",
        )
    ]
    assert rebuilt == payload


def test_resolve_config_layers_includes_board_overlay_only_when_present(tmp_path) -> None:
    """Board overlays should be appended only when the file exists."""

    board_dir = tmp_path / "boards" / "rpi-zero-2w" / "audio"
    board_dir.mkdir(parents=True)
    overlay = board_dir / "music.yaml"
    overlay.write_text("audio: {}\n", encoding="utf-8")

    layers = resolve_config_layers(tmp_path, "rpi-zero-2w", Path("audio/music.yaml"))

    assert layers == (tmp_path / "audio" / "music.yaml", overlay)


def test_resolve_config_board_prefers_explicit_value(monkeypatch) -> None:
    """An explicit board argument should beat env-based auto-detection."""

    monkeypatch.setenv("YOYOPOD_CONFIG_BOARD", "env-board")

    assert resolve_config_board(explicit_board="explicit-board") == "explicit-board"
