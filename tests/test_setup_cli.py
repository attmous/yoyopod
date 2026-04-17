"""Tests for repo-owned setup/bootstrap helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("typer")

import yoyopod.cli.setup as setup_cli_module
from yoyopod.setup_contract import RUNTIME_REQUIRED_CONFIG_FILES
from yoyopod.cli.setup import (
    SetupCheck,
    build_host_setup_commands,
    build_pi_setup_commands,
    collect_host_setup_checks,
    collect_pi_setup_checks,
    pi_package_list,
)


def test_pi_package_list_splits_core_and_feature_packages() -> None:
    assert pi_package_list(with_voice=False, with_network=False, with_pisugar=False) == (
        "mpv",
        "ffmpeg",
        "liblinphone-dev",
        "pkg-config",
        "cmake",
        "alsa-utils",
        "i2c-tools",
    )
    assert pi_package_list(with_voice=True, with_network=True, with_pisugar=True) == (
        "mpv",
        "ffmpeg",
        "liblinphone-dev",
        "pkg-config",
        "cmake",
        "alsa-utils",
        "i2c-tools",
        "espeak-ng",
        "ppp",
        "pisugar-server",
    )


def test_build_host_setup_commands_runs_uv_sync_by_default() -> None:
    commands = build_host_setup_commands()

    assert commands == (
        setup_cli_module.SetupCommand("uv-sync-dev", ("uv", "sync", "--extra", "dev")),
    )
    assert build_host_setup_commands(skip_sync=True) == ()


def test_build_pi_setup_commands_include_install_sync_and_builds() -> None:
    commands = build_pi_setup_commands(
        with_voice=True,
        with_network=True,
        with_pisugar=True,
    )

    assert commands[0].command == ("sudo", "apt", "update")
    assert commands[1].command == (
        "sudo",
        "apt",
        "install",
        "-y",
        "mpv",
        "ffmpeg",
        "liblinphone-dev",
        "pkg-config",
        "cmake",
        "alsa-utils",
        "i2c-tools",
        "espeak-ng",
        "ppp",
        "pisugar-server",
    )
    assert commands[2].command == ("uv", "sync", "--extra", "dev")
    assert commands[3].command == ("uv", "run", "yoyoctl", "build", "liblinphone")
    assert commands[4].command == ("uv", "run", "yoyoctl", "build", "lvgl")


def test_collect_host_setup_checks_cover_required_tools_modules_and_config(
    tmp_path, monkeypatch
) -> None:
    tracked_config = (
        tmp_path / "config" / "app" / "core.yaml",
        tmp_path / "config" / "audio" / "music.yaml",
        tmp_path / "config" / "device" / "hardware.yaml",
        tmp_path / "config" / "power" / "backend.yaml",
        tmp_path / "config" / "network" / "cellular.yaml",
        tmp_path / "config" / "voice" / "assistant.yaml",
        tmp_path / "config" / "communication" / "calling.yaml",
        tmp_path / "config" / "communication" / "messaging.yaml",
        tmp_path / "config" / "communication" / "calling.secrets.example.yaml",
        tmp_path / "config" / "communication" / "integrations" / "liblinphone_factory.conf",
        tmp_path / "config" / "people" / "directory.yaml",
        tmp_path / "config" / "people" / "contacts.seed.yaml",
        tmp_path / "deploy" / "pi-deploy.yaml",
    )
    for path in tracked_config:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok\n", encoding="utf-8")

    monkeypatch.setattr(setup_cli_module, "TRACKED_CONFIG_PATHS", tracked_config)
    monkeypatch.setattr(
        setup_cli_module.shutil,
        "which",
        lambda program: (
            f"/usr/bin/{program}" if program in {"git", "uv", "ssh", "rsync", "gh"} else None
        ),
    )
    monkeypatch.setattr(
        setup_cli_module.importlib.util,
        "find_spec",
        lambda module_name: SimpleNamespace(name=module_name),
    )

    checks = collect_host_setup_checks(with_remote_tools=True, with_github=True)

    assert all(check.ok for check in checks)
    assert any(check.label == "git" for check in checks)
    assert any(check.label == "pytest" for check in checks)
    assert any(check.label == "gh" for check in checks)


def test_collect_pi_setup_checks_require_packages_native_artifacts_and_service(
    tmp_path, monkeypatch
) -> None:
    tracked_config = (
        tmp_path / "config" / "app" / "core.yaml",
        tmp_path / "config" / "audio" / "music.yaml",
        tmp_path / "config" / "device" / "hardware.yaml",
        tmp_path / "config" / "power" / "backend.yaml",
        tmp_path / "config" / "network" / "cellular.yaml",
        tmp_path / "config" / "voice" / "assistant.yaml",
        tmp_path / "config" / "communication" / "calling.yaml",
        tmp_path / "config" / "communication" / "messaging.yaml",
        tmp_path / "config" / "communication" / "calling.secrets.example.yaml",
        tmp_path / "config" / "communication" / "integrations" / "liblinphone_factory.conf",
        tmp_path / "config" / "people" / "directory.yaml",
        tmp_path / "config" / "people" / "contacts.seed.yaml",
        tmp_path / "deploy" / "pi-deploy.yaml",
    )
    native_artifacts = (
        tmp_path / "build" / "libyoyopod_lvgl_shim.so",
        tmp_path / "build" / "libyoyopod_liblinphone_shim.so",
    )
    for path in (*tracked_config, *native_artifacts):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok\n", encoding="utf-8")

    monkeypatch.setattr(setup_cli_module, "TRACKED_CONFIG_PATHS", tracked_config)
    monkeypatch.setattr(setup_cli_module, "NATIVE_ARTIFACTS", native_artifacts)
    monkeypatch.setattr(
        setup_cli_module.shutil,
        "which",
        lambda program: "/usr/bin/uv" if program == "uv" else None,
    )

    def fake_run(command, check=False, capture_output=False, text=False):
        if command[:2] == ["dpkg-query", "-W"]:
            return SimpleNamespace(returncode=0, stdout="install ok installed", stderr="")
        if command[:3] == ["systemctl", "is-active", "--quiet"]:
            return SimpleNamespace(returncode=0)
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(setup_cli_module.subprocess, "run", fake_run)

    checks = collect_pi_setup_checks(with_voice=True, with_network=True, with_pisugar=True)

    assert all(check.ok for check in checks)
    assert any(check.label == "apt:mpv" for check in checks)
    assert any(check.label == "apt:pisugar-server" for check in checks)
    assert any(check.label == "service:pisugar-server" for check in checks)


def test_collect_host_setup_checks_fail_when_power_backend_config_is_missing(
    tmp_path, monkeypatch
) -> None:
    tracked_config = (
        tmp_path / "config" / "app" / "core.yaml",
        tmp_path / "config" / "audio" / "music.yaml",
        tmp_path / "config" / "device" / "hardware.yaml",
        tmp_path / "config" / "power" / "backend.yaml",
        tmp_path / "config" / "network" / "cellular.yaml",
        tmp_path / "config" / "voice" / "assistant.yaml",
        tmp_path / "config" / "communication" / "calling.yaml",
        tmp_path / "config" / "communication" / "messaging.yaml",
        tmp_path / "config" / "communication" / "calling.secrets.example.yaml",
        tmp_path / "config" / "communication" / "integrations" / "liblinphone_factory.conf",
        tmp_path / "config" / "people" / "directory.yaml",
        tmp_path / "config" / "people" / "contacts.seed.yaml",
        tmp_path / "deploy" / "pi-deploy.yaml",
    )
    for path in tracked_config:
        if path.as_posix().endswith("config/power/backend.yaml"):
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok\n", encoding="utf-8")

    monkeypatch.setattr(setup_cli_module, "TRACKED_CONFIG_PATHS", tracked_config)
    monkeypatch.setattr(
        setup_cli_module.shutil,
        "which",
        lambda program: f"/usr/bin/{program}" if program in {"git", "uv"} else None,
    )
    monkeypatch.setattr(
        setup_cli_module.importlib.util,
        "find_spec",
        lambda module_name: SimpleNamespace(name=module_name),
    )

    checks = collect_host_setup_checks(with_remote_tools=False, with_github=False)

    power_check = next(
        check
        for check in checks
        if check.label == setup_cli_module._display_path(tracked_config[3])
    )
    assert power_check.ok is False
    assert power_check.detail == "missing"


def test_tracked_setup_config_paths_cover_runtime_required_config_contract() -> None:
    tracked = {
        setup_cli_module._display_path(path) for path in setup_cli_module.TRACKED_CONFIG_PATHS
    }

    assert {path.as_posix() for path in RUNTIME_REQUIRED_CONFIG_FILES}.issubset(tracked)


def test_report_checks_returns_failure_for_missing_items() -> None:
    checks = (
        SetupCheck("ok-check", True, "present"),
        SetupCheck("bad-check", False, "missing"),
    )

    assert setup_cli_module._report_checks(checks) == 1
