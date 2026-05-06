from __future__ import annotations

import configparser
from pathlib import Path


UNITS_DIR = Path(__file__).resolve().parents[2] / "deploy" / "systemd"


def _parse(unit_name: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.read(UNITS_DIR / unit_name)
    return parser


def test_prod_unit_references_launch_script() -> None:
    cfg = _parse("yoyopod-prod.service")
    assert cfg["Service"]["WorkingDirectory"] == "/"
    assert "YOYOPOD_ROOT" in cfg["Service"]["ExecStart"]
    assert "/opt/yoyopod-prod" in cfg["Service"]["ExecStart"]
    assert "/current/bin/launch" in cfg["Service"]["ExecStart"]
    assert cfg["Unit"]["Conflicts"] == "yoyopod-dev.service"


def test_prod_unit_has_onfailure_rollback() -> None:
    cfg = _parse("yoyopod-prod.service")
    assert cfg["Unit"]["OnFailure"] == "yoyopod-prod-rollback.service"


def test_prod_unit_has_start_limit_burst() -> None:
    cfg = _parse("yoyopod-prod.service")
    assert cfg["Unit"]["StartLimitBurst"] == "3"
    assert cfg["Unit"]["StartLimitIntervalSec"] == "300"


def test_prod_rollback_unit_calls_rollback_script() -> None:
    cfg = _parse("yoyopod-prod-rollback.service")
    assert cfg["Service"]["EnvironmentFile"] == "-/etc/default/yoyopod-prod"
    assert "YOYOPOD_ROOT" in cfg["Service"]["ExecStart"]
    assert "/opt/yoyopod-prod" in cfg["Service"]["ExecStart"]
    assert "/bin/rollback.sh" in cfg["Service"]["ExecStart"]
    assert cfg["Service"]["Type"] == "oneshot"


def test_prod_rollback_unit_has_its_own_start_limit() -> None:
    cfg = _parse("yoyopod-prod-rollback.service")
    assert cfg["Unit"]["StartLimitBurst"] == "2"


def test_dev_unit_references_checkout_and_venv_for_native_refresh() -> None:
    cfg = _parse("yoyopod-dev.service")
    unit_text = (UNITS_DIR / "yoyopod-dev.service").read_text(encoding="utf-8")
    exec_start = cfg["Service"]["ExecStart"]
    exec_start_pre = cfg["Service"]["ExecStartPre"]

    assert cfg["Service"]["WorkingDirectory"] == "/"
    assert cfg["Service"]["EnvironmentFile"] == "-/etc/default/yoyopod-dev"
    assert "Environment=PYTHONUNBUFFERED=1" in unit_text
    assert "Environment=HOME=/root" in unit_text
    assert cfg["Unit"]["Conflicts"] == "yoyopod-prod.service"
    assert "install -d -m 700" in exec_start_pre
    assert ".local/share/linphone" in exec_start_pre
    assert ".config/linphone" in exec_start_pre
    assert "YOYOPOD_DEV_CHECKOUT" in exec_start
    assert "/opt/yoyopod-dev/checkout" in exec_start
    assert "YOYOPOD_DEV_VENV" in exec_start_pre
    assert "/opt/yoyopod-dev/venv" in exec_start_pre
    assert "LD_LIBRARY_PATH" in exec_start_pre
    assert "LD_LIBRARY_PATH" in exec_start
    assert "yoyopod/ui/lvgl_binding/native/build" in exec_start
    assert "-m yoyopod_cli.main build ensure-native" in exec_start_pre


def test_dev_unit_runs_rust_runtime_directly() -> None:
    cfg = _parse("yoyopod-dev.service")
    exec_start = cfg["Service"]["ExecStart"]

    assert "YOYOPOD_DEV_" + "RUNTIME" not in exec_start
    assert "device/runtime/build/yoyopod-runtime" in exec_start
    assert '--config-dir "$$CHECKOUT/config" --hardware whisplay' in exec_start
    assert "yoyopod.py" not in exec_start
