from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from yoyopod_cli.main import app as root_app
from yoyopod_cli.paths import LanePaths, SlotPaths
from yoyopod_cli.remote_mode import (
    _build_activate,
    _build_deactivate,
    _build_status,
)


def test_activate_dev_stops_prod_lane_before_starting_dev() -> None:
    lanes = LanePaths()
    command = _build_activate("dev", lanes)

    stop_ota = command.index("disable --now yoyopod-prod-ota.timer")
    stop_prod = command.index("disable --now yoyopod-prod.service")
    stop_legacy_template = command.index("yoyopod@*.service")
    stop_manual = command.index("manual_pids=$(pgrep -f")
    start_dev = command.index("enable --now yoyopod-dev.service")

    assert stop_ota < start_dev
    assert stop_prod < start_dev
    assert stop_legacy_template < start_dev
    assert stop_manual < start_dev
    assert "reset-failed yoyopod-dev.service" in command
    assert "yoyopod-slot.service" in command
    assert "/etc/systemd/system/yoyopod@.service" in command
    assert "/etc/systemd/system/yoyopod-slot.service" in command
    assert "/etc/default/yoyopod" in command


def test_activate_prod_stops_dev_lane_before_starting_prod() -> None:
    lanes = LanePaths()
    command = _build_activate("prod", lanes)

    stop_dev = command.index("disable --now yoyopod-dev.service")
    stop_legacy_slot = command.index("disable --now yoyopod-slot.service")
    stop_legacy_template = command.index("yoyopod@*.service")
    stop_manual = command.index("manual_pids=$(pgrep -f")
    start_prod = command.index("enable --now yoyopod-prod.service")

    assert stop_dev < start_prod
    assert stop_legacy_slot < start_prod
    assert stop_legacy_template < start_prod
    assert stop_manual < start_prod
    assert "reset-failed yoyopod-prod.service" in command
    assert "enable --now yoyopod-prod-ota.timer" in command


def test_deactivate_prod_stops_app_and_ota_units() -> None:
    command = _build_deactivate("prod", LanePaths())

    assert "disable --now yoyopod-prod.service" in command
    assert "disable --now yoyopod-prod-ota.timer" in command
    assert "disable --now yoyopod-prod-ota.service" in command
    assert "yoyopod-dev.service" not in command


def test_status_reports_all_lane_units_and_roots() -> None:
    command = _build_status(LanePaths(), SlotPaths())

    assert "active_lane=" in command
    assert "yoyopod-dev.service" in command
    assert "yoyopod-prod.service" in command
    assert "yoyopod-prod-ota.timer" in command
    assert "/opt/yoyopod-dev/checkout" in command
    assert "/opt/yoyopod-prod/current" in command


def test_status_detects_legacy_units_and_manual_processes() -> None:
    command = _build_status(LanePaths(), SlotPaths())

    assert "yoyopod@*.service" in command
    assert "yoyopod-slot.service" in command
    assert "legacy_units=" in command
    assert "pgrep -af" in command
    assert "manual_processes=" in command
    assert "manual-process" in command
    assert "active_lane=conflict" in command


def test_activate_purges_loaded_and_enabled_legacy_template_units() -> None:
    command = _build_activate("dev", LanePaths())

    list_units = command.index("systemctl list-units --type=service --all --plain --no-legend")
    list_unit_files = command.index("systemctl list-unit-files --type=service --plain --no-legend")
    disable = command.index("sudo systemctl disable --now $legacy_units")
    start_dev = command.index("enable --now yoyopod-dev.service")

    assert list_units < disable < start_dev
    assert list_unit_files < disable < start_dev


def test_activate_stops_unmanaged_app_processes_before_enabling_lane() -> None:
    command = _build_activate("prod", LanePaths())

    cleanup = command.index("manual_pids=$(pgrep -f")
    start_prod = command.index("enable --now yoyopod-prod.service")

    assert cleanup < start_prod
    assert "python(3)? .*yoyopod(\\.py|\\.main)" in command
    assert "kill $manual_pids" in command


def test_status_checks_only_active_legacy_template_units() -> None:
    command = _build_status(LanePaths(), SlotPaths())

    assert "list-units --type=service --state=active --plain --no-legend" in command
    assert "list-units --type=service --all --plain --no-legend" not in command


def test_status_counts_legacy_slot_service_as_lane_owner() -> None:
    command = _build_status(LanePaths(), SlotPaths())

    slot_check_pos = command.index('legacy_slot_active=$(systemctl is-active "$legacy_slot_unit"')
    lane_count_pos = command.index('if [ -n "$legacy_units" ]; then lane_count=')

    assert slot_check_pos < lane_count_pos
    assert "legacy_slot_unit=yoyopod-slot.service" in command
    assert 'legacy_units="${legacy_units:+$legacy_units }$legacy_slot_unit"' in command


def test_status_reports_prod_ota_conflict_when_dev_is_active() -> None:
    command = _build_status(LanePaths(), SlotPaths())

    assert "prod_ota_conflict=" in command
    assert "prod-ota-active-while-dev" in command


def test_status_uses_slot_root_for_prod_current_probe() -> None:
    command = _build_status(
        LanePaths(prod_root="/wrong-lane-prod"),
        SlotPaths(root="/srv/yoyopod-prod"),
    )

    assert "/srv/yoyopod-prod/current" in command
    assert "/wrong-lane-prod/current" not in command


@patch("yoyopod_cli.remote_mode.run_remote")
def test_remote_mode_cli_uses_parent_remote_connection(run_remote_mock: MagicMock) -> None:
    run_remote_mock.return_value = 0

    result = CliRunner().invoke(
        root_app,
        ["remote", "--host", "rpi-zero", "mode", "activate", "dev"],
    )

    assert result.exit_code == 0, result.output
    assert run_remote_mock.call_args[0][0].host == "rpi-zero"
    assert "enable --now yoyopod-dev.service" in run_remote_mock.call_args[0][1]
    assert run_remote_mock.call_args.kwargs["workdir"] is None
