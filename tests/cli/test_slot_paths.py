from __future__ import annotations

from pathlib import Path

import yaml

from yoyopod_cli.paths import SlotPaths, load_slot_paths


def test_defaults_match_spec() -> None:
    slot = SlotPaths()
    assert slot.root == "/opt/yoyopod-prod"
    assert slot.releases_subdir == "releases"
    assert slot.state_subdir == "state"
    assert slot.current_link == "current"
    assert slot.previous_link == "previous"


def test_loads_overrides_from_yaml(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text(yaml.safe_dump({"slot": {"root": "/opt/yoyopod"}}))
    local = tmp_path / "local.yaml"
    local.write_text(yaml.safe_dump({"slot": {"root": "/srv/yoyopod-alt"}}))
    result = load_slot_paths(base_path=base, local_path=local)
    assert result.root == "/srv/yoyopod-alt"


def test_absent_slot_section_uses_defaults(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text("host: example.com\nuser: pi\n")
    result = load_slot_paths(base_path=base, local_path=tmp_path / "missing.yaml")
    assert result.root == "/opt/yoyopod-prod"


def test_releases_dir_and_state_dir_helpers() -> None:
    slot = SlotPaths()
    assert slot.releases_dir() == "/opt/yoyopod-prod/releases"
    assert slot.state_dir() == "/opt/yoyopod-prod/state"
    assert slot.current_path() == "/opt/yoyopod-prod/current"
