"""Test top-level aliases for hot-path commands."""

from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from yoyopod_cli.main import app


def test_all_shortcuts_listed_in_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("deploy", "status", "logs", "restart", "validate"):
        assert cmd in result.output, f"missing top-level shortcut: {cmd}"


def test_status_alias_invokes_same_handler(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "yoyopod_cli.remote_ops.run_remote",
        lambda conn, cmd, tty=False: (calls.append(cmd), 0)[1],
    )
    monkeypatch.setenv("YOYOPOD_PI_HOST", "rpi-zero")

    runner = CliRunner()
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert "git rev-parse HEAD" in calls[0]


def test_deploy_alias_invokes_sync(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "yoyopod_cli.remote_ops.run_remote",
        lambda conn, cmd, tty=False: (calls.append(cmd), 0)[1],
    )
    monkeypatch.setenv("YOYOPOD_PI_HOST", "rpi-zero")

    runner = CliRunner()
    result = runner.invoke(app, ["deploy"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert "git fetch --prune origin" in calls[0]
    assert "git clean -fd" in calls[0]


def test_logs_alias_respects_follow_flag(monkeypatch) -> None:
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        "yoyopod_cli.remote_ops.run_remote",
        lambda conn, cmd, tty=False: (calls.append((cmd, tty)), 0)[1],
    )
    monkeypatch.setenv("YOYOPOD_PI_HOST", "rpi-zero")

    runner = CliRunner()
    result = runner.invoke(app, ["logs", "--follow"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert calls[0][1] is True  # tty=follow


def test_validate_alias_with_flags(monkeypatch) -> None:
    calls: list[str] = []

    def fake_local(argv: list[str]) -> SimpleNamespace:
        if argv == ["git", "show-ref", "--verify", "--quiet", "refs/heads/main"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if argv == ["git", "rev-list", "--count", "origin/main..main"]:
            return SimpleNamespace(returncode=0, stdout="0\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        "yoyopod_cli.remote_validate.run_local_capture",
        fake_local,
    )
    monkeypatch.setattr(
        "yoyopod_cli.remote_validate.run_remote",
        lambda conn, cmd, tty=False: (calls.append(cmd), 0)[1],
    )
    monkeypatch.setenv("YOYOPOD_PI_HOST", "rpi-zero")

    runner = CliRunner()
    result = runner.invoke(app, ["validate", "--with-music", "--with-voip"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert "/opt/yoyopod-dev/venv/bin/python -m yoyopod_cli.main pi validate music" in calls[0]
    assert "/opt/yoyopod-dev/venv/bin/python -m yoyopod_cli.main pi validate voip" in calls[0]


def test_validate_alias_with_power_and_rtc_flags(monkeypatch) -> None:
    calls: list[str] = []

    def fake_local(argv: list[str]) -> SimpleNamespace:
        if argv == ["git", "show-ref", "--verify", "--quiet", "refs/heads/main"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if argv == ["git", "rev-list", "--count", "origin/main..main"]:
            return SimpleNamespace(returncode=0, stdout="0\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        "yoyopod_cli.remote_validate.run_local_capture",
        fake_local,
    )
    monkeypatch.setattr(
        "yoyopod_cli.remote_validate.run_remote",
        lambda conn, cmd, tty=False: (calls.append(cmd), 0)[1],
    )
    monkeypatch.setenv("YOYOPOD_PI_HOST", "rpi-zero")

    runner = CliRunner()
    result = runner.invoke(app, ["validate", "--with-power", "--with-rtc"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert (
        "/opt/yoyopod-dev/venv/bin/python -m yoyopod_cli.main pi validate smoke "
        "--with-power --with-rtc"
        in calls[0]
    )
