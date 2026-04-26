from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from yoyopod_cli import pi_validate


def _collect_option_names(click_cmd: object) -> set[str]:
    names: set[str] = set()
    for param in getattr(click_cmd, "params", []):
        names.update(getattr(param, "opts", []))
    return names


def test_load_env_file_parses_service_style_assignments(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / "yoyopod-dev.env"
    env_file.write_text(
        "\n".join(
            [
                "# comment",
                "OPENAI_API_KEY='sk-test'",
                'YOYOPOD_VOICE_MODE="cloud"',
                "YOYOPOD_VOICE_WORKER_ENABLED=true",
                "MALFORMED",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("YOYOPOD_VOICE_MODE", raising=False)
    monkeypatch.delenv("YOYOPOD_VOICE_WORKER_ENABLED", raising=False)

    loaded = pi_validate._load_cloud_voice_env_file(env_file)

    assert loaded == ["OPENAI_API_KEY", "YOYOPOD_VOICE_MODE", "YOYOPOD_VOICE_WORKER_ENABLED"]
    assert pi_validate.os.environ["OPENAI_API_KEY"] == "sk-test"
    assert pi_validate.os.environ["YOYOPOD_VOICE_MODE"] == "cloud"


def test_cloud_voice_settings_check_requires_cloud_worker_mode() -> None:
    settings = pi_validate.VoiceSettings(
        mode="local",
        stt_backend="vosk",
        tts_backend="espeak-ng",
        cloud_worker_enabled=False,
    )

    result = pi_validate._cloud_voice_settings_check(settings, provider="mock")

    assert result.status == "fail"
    assert "mode=local" in result.details


def test_cloud_voice_settings_check_redacts_openai_key(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    settings = pi_validate.VoiceSettings(
        mode="cloud",
        stt_backend="cloud-worker",
        tts_backend="cloud-worker",
        cloud_worker_enabled=True,
        cloud_worker_provider="openai",
        speaker_device_id="playback",
        capture_device_id="capture",
    )

    result = pi_validate._cloud_voice_settings_check(settings, provider="openai")

    assert result.status == "pass"
    assert "OPENAI_API_KEY=set" in result.details
    assert "sk-secret" not in result.details


def test_cloud_voice_command_match_check_reports_transcript() -> None:
    result = pi_validate._cloud_voice_command_match_check("please play music")

    assert result.status == "pass"
    assert "intent=play_music" in result.details
    assert "please play music" in result.details


def test_cloud_voice_command_help_exposes_repeatable_options() -> None:
    result = CliRunner().invoke(pi_validate.app, ["cloud-voice", "--help"], terminal_width=200)

    assert result.exit_code == 0
    import typer.main

    click_cmd = typer.main.get_command(pi_validate.app)
    cloud_voice_cmd = click_cmd.commands["cloud-voice"]  # type: ignore[attr-defined]
    names = _collect_option_names(cloud_voice_cmd)
    assert "--cycles" in names
    assert "--phrase" in names
    assert "--env-file" in names
