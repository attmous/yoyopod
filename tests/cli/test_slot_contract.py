from __future__ import annotations

from pathlib import Path

import pytest

from yoyopod_cli.slot_contract import (
    APP_NATIVE_RUNTIME_ARTIFACTS,
    SLOT_PYTHON_BIN,
    SLOT_PYTHON_STDLIB_MARKER,
    SLOT_VENV_PYTHON,
    detect_self_contained_python_version,
    is_self_contained_slot,
    missing_hydrated_runtime_paths,
    missing_self_contained_paths,
    slot_python_bin,
    slot_python_stdlib_marker,
)


def test_self_contained_contract_rejects_symlinked_launch_python(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slot = tmp_path / "slot"
    python_bin = slot / SLOT_VENV_PYTHON
    python_bin.parent.mkdir(parents=True)
    python_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    runtime_python = slot / SLOT_PYTHON_BIN
    runtime_python.parent.mkdir(parents=True, exist_ok=True)
    runtime_python.write_text("python\n", encoding="utf-8")
    runtime_stdlib = slot / SLOT_PYTHON_STDLIB_MARKER
    runtime_stdlib.parent.mkdir(parents=True, exist_ok=True)
    runtime_stdlib.write_text("# stdlib marker\n", encoding="utf-8")
    for relative in APP_NATIVE_RUNTIME_ARTIFACTS:
        target = slot / "app" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("shim\n", encoding="utf-8")

    original_is_symlink = Path.is_symlink

    def fake_is_symlink(path: Path) -> bool:
        if path == python_bin:
            return True
        return original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)

    assert missing_self_contained_paths(slot) == (SLOT_VENV_PYTHON,)
    assert is_self_contained_slot(slot) is False


def test_self_contained_contract_derives_python_runtime_paths(tmp_path: Path) -> None:
    slot = tmp_path / "slot"
    python_bin = slot / SLOT_VENV_PYTHON
    python_bin.parent.mkdir(parents=True)
    python_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    runtime_python = slot / slot_python_bin("3.11")
    runtime_python.parent.mkdir(parents=True, exist_ok=True)
    runtime_python.write_text("python\n", encoding="utf-8")
    runtime_stdlib = slot / slot_python_stdlib_marker("3.11")
    runtime_stdlib.parent.mkdir(parents=True, exist_ok=True)
    runtime_stdlib.write_text("# stdlib marker\n", encoding="utf-8")
    for relative in APP_NATIVE_RUNTIME_ARTIFACTS:
        target = slot / "app" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("shim\n", encoding="utf-8")

    assert missing_self_contained_paths(slot, "3.11") == ()
    assert is_self_contained_slot(slot, "3.11") is True
    assert detect_self_contained_python_version(slot) == "3.11"
    assert slot_python_bin("3.12") in missing_self_contained_paths(slot)


def test_hydrated_runtime_contract_allows_target_python_venv(tmp_path: Path) -> None:
    slot = tmp_path / "slot"
    python_bin = slot / SLOT_VENV_PYTHON
    python_bin.parent.mkdir(parents=True)
    python_bin.write_text("#!/usr/bin/python3\n", encoding="utf-8")
    for relative in APP_NATIVE_RUNTIME_ARTIFACTS:
        target = slot / "app" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("shim\n", encoding="utf-8")

    assert missing_hydrated_runtime_paths(slot) == ()
    assert detect_self_contained_python_version(slot) is None
