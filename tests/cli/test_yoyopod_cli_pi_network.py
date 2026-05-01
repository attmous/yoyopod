from __future__ import annotations

import io
from typing import Any

from typer.testing import CliRunner

import yoyopod_cli.pi.network as network_cli

app = network_cli.app


def test_probe_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["probe", "--help"])
    assert result.exit_code == 0


def test_status_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["status", "--help"])
    assert result.exit_code == 0


def test_gps_command_cut() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["gps", "--help"])
    assert result.exit_code != 0


def test_help_lists_only_probe_and_status() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "probe" in result.output
    assert "status" in result.output
    assert "gps" not in result.output


def test_probe_uses_rust_network_snapshot(monkeypatch) -> None:
    snapshots: list[str] = []

    def fake_request(config_dir: str, *, timeout_seconds: float = 10.0) -> dict[str, Any]:
        snapshots.append(config_dir)
        return {
            "enabled": True,
            "state": "registered",
            "error_code": "",
            "error_message": "",
            "views": {
                "cli": {
                    "probe_ok": True,
                    "probe_error": "",
                    "status_lines": [
                        "phase=registered",
                        "sim_ready=True",
                        "carrier=Telekom.de",
                        "network_type=4G",
                        "signal_csq=20",
                        "signal_bars=3",
                        "ppp_up=False",
                        "error=none",
                    ],
                }
            },
        }

    monkeypatch.setattr(network_cli, "_request_network_snapshot", fake_request)

    result = CliRunner().invoke(app, ["probe", "--config-dir", "config/test-device"])

    assert result.exit_code == 0
    assert "Modem OK" in result.output
    assert snapshots == ["config/test-device"]


def test_status_uses_rust_network_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(
        network_cli,
        "_request_network_snapshot",
        lambda _config_dir, *, timeout_seconds=10.0: {
            "enabled": True,
            "state": "online",
            "sim_ready": True,
            "carrier": "Telekom.de",
            "network_type": "4G",
            "signal": {"csq": 20, "bars": 3},
            "ppp": {"up": True},
            "error_code": "",
            "error_message": "",
            "views": {
                "cli": {
                    "probe_ok": True,
                    "probe_error": "",
                    "status_lines": [
                        "phase=online",
                        "sim_ready=True",
                        "carrier=Telekom.de",
                        "network_type=4G",
                        "signal_csq=20",
                        "signal_bars=3",
                        "ppp_up=True",
                        "error=none",
                    ],
                }
            },
        },
    )

    result = CliRunner().invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Rust Network Host Status" in result.output
    assert "phase=online" in result.output
    assert "ppp_up=True" in result.output


class _FakeProcess:
    def __init__(self, *, stdout_text: str = "", stderr_text: str = "") -> None:
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(stdout_text)
        self.stderr = io.StringIO(stderr_text)
        self._returncode: int | None = None

    def poll(self) -> int | None:
        return self._returncode

    def wait(self, timeout: float | None = None) -> int:
        _ = timeout
        self._returncode = 0
        return 0

    def terminate(self) -> None:
        self._returncode = 0

    def kill(self) -> None:
        self._returncode = -9


def _combined_output(result) -> str:
    return f"{getattr(result, 'stdout', '') or ''}{getattr(result, 'stderr', '') or ''}{result.output}"


def test_request_network_snapshot_times_out_when_worker_stays_silent(monkeypatch) -> None:
    monkeypatch.setattr(
        network_cli,
        "_spawn_network_worker",
        lambda _config_dir: _FakeProcess(),
    )

    try:
        network_cli._request_network_snapshot("config/test-device", timeout_seconds=0.1)
    except RuntimeError as exc:
        assert "timed out waiting for network worker snapshot" in str(exc)
    else:
        raise AssertionError("expected timeout from silent worker")


def test_probe_reports_snapshot_error_before_disabled_flag(monkeypatch) -> None:
    monkeypatch.setattr(
        network_cli,
        "_request_network_snapshot",
        lambda _config_dir, *, timeout_seconds=10.0: {
            "enabled": False,
            "error_code": "config_load_failed",
            "error_message": "config load failed",
            "views": {
                "cli": {
                    "probe_ok": False,
                    "probe_error": "config load failed",
                    "status_lines": [],
                }
            },
        },
    )

    result = CliRunner().invoke(app, ["probe"])

    assert result.exit_code == 1
    assert "config load failed" in _combined_output(result).lower()


def test_status_reports_snapshot_error_before_disabled_flag(monkeypatch) -> None:
    monkeypatch.setattr(
        network_cli,
        "_request_network_snapshot",
        lambda _config_dir, *, timeout_seconds=10.0: {
            "enabled": False,
            "error_code": "config_load_failed",
            "error_message": "config load failed",
            "views": {
                "cli": {
                    "probe_ok": False,
                    "probe_error": "config load failed",
                    "status_lines": [],
                }
            },
        },
    )

    result = CliRunner().invoke(app, ["status"])

    assert result.exit_code == 1
    assert "config load failed" in _combined_output(result).lower()


def test_probe_uses_rust_cli_projection(monkeypatch) -> None:
    monkeypatch.setattr(
        network_cli,
        "_request_network_snapshot",
        lambda _config_dir, *, timeout_seconds=10.0: {
            "enabled": False,
            "error_code": "",
            "error_message": "",
            "views": {"cli": {"probe_ok": True, "probe_error": "", "status_lines": []}},
        },
    )

    result = CliRunner().invoke(app, ["probe"])

    assert result.exit_code == 0
    assert "Modem OK" in result.output


def test_status_uses_rust_cli_projection(monkeypatch) -> None:
    monkeypatch.setattr(
        network_cli,
        "_request_network_snapshot",
        lambda _config_dir, *, timeout_seconds=10.0: {
            "enabled": False,
            "error_code": "",
            "error_message": "",
            "views": {
                "cli": {
                    "probe_ok": True,
                    "probe_error": "",
                    "status_lines": [
                        "phase=online",
                        "sim_ready=True",
                        "carrier=Telekom.de",
                        "network_type=4G",
                        "signal_csq=20",
                        "signal_bars=3",
                        "ppp_up=True",
                        "error=none",
                    ],
                }
            },
        },
    )

    result = CliRunner().invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Rust Network Host Status" in result.output
    assert "phase=online" in result.output
    assert "ppp_up=True" in result.output
