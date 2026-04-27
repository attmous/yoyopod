from __future__ import annotations

import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from yoyopod_cli.pi.validate import cloud_voice as pi_validate_cv
from yoyopod_cli.pi.validate import app as pi_validate_app


def _collect_option_names(click_cmd: object) -> set[str]:
    names: set[str] = set()
    for param in getattr(click_cmd, "params", []):
        names.update(getattr(param, "opts", []))
    return names


def _write_wav(path: Path, *, sample_rate_hz: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(b"\x00\x00" * sample_rate_hz)


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

    loaded = pi_validate_cv._load_cloud_voice_env_file(env_file)

    assert loaded == ["OPENAI_API_KEY", "YOYOPOD_VOICE_MODE", "YOYOPOD_VOICE_WORKER_ENABLED"]
    assert pi_validate_cv.os.environ["OPENAI_API_KEY"] == "sk-test"
    assert pi_validate_cv.os.environ["YOYOPOD_VOICE_MODE"] == "cloud"


def test_cloud_voice_settings_check_requires_cloud_worker_mode() -> None:
    settings = pi_validate_cv.VoiceSettings(
        mode="local",
        stt_backend="vosk",
        tts_backend="espeak-ng",
        cloud_worker_enabled=False,
    )

    result = pi_validate_cv._cloud_voice_settings_check(settings, provider="mock")

    assert result.status == "fail"
    assert "mode=local" in result.details


def test_cloud_voice_settings_check_redacts_openai_key(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    settings = pi_validate_cv.VoiceSettings(
        mode="cloud",
        stt_backend="cloud-worker",
        tts_backend="cloud-worker",
        cloud_worker_enabled=True,
        cloud_worker_provider="openai",
        speaker_device_id="playback",
        capture_device_id="capture",
    )

    result = pi_validate_cv._cloud_voice_settings_check(settings, provider="openai")

    assert result.status == "pass"
    assert "OPENAI_API_KEY=set" in result.details
    assert "sk-secret" not in result.details


def test_cloud_voice_command_match_check_reports_transcript() -> None:
    result = pi_validate_cv._cloud_voice_command_match_check("please play music")

    assert result.status == "pass"
    assert "intent=play_music" in result.details
    assert "please play music" in result.details


def test_cloud_voice_command_help_exposes_repeatable_options() -> None:
    result = CliRunner().invoke(pi_validate_app, ["cloud-voice", "--help"], terminal_width=200)

    assert result.exit_code == 0
    import typer.main

    click_cmd = typer.main.get_command(pi_validate_app)
    cloud_voice_cmd = click_cmd.commands["cloud-voice"]  # type: ignore[attr-defined]
    names = _collect_option_names(cloud_voice_cmd)
    assert "--cycles" in names
    assert "--phrase" in names
    assert "--env-file" in names
    assert "--acoustic-loopback" in names


def test_cloud_voice_worker_argv_preserves_configured_arguments(monkeypatch) -> None:
    monkeypatch.setattr(pi_validate_cv.shutil, "which", lambda binary: f"/usr/bin/{binary}")
    config_manager = SimpleNamespace(
        get_voice_settings=lambda: SimpleNamespace(
            worker=SimpleNamespace(argv=["python3", "-m", "fake.worker"])
        )
    )

    argv = pi_validate_cv._resolve_cloud_voice_worker_argv(config_manager, "")

    assert argv == ["/usr/bin/python3", "-m", "fake.worker"]


def test_cloud_voice_worker_binary_check_accepts_path_executable(monkeypatch) -> None:
    monkeypatch.setattr(pi_validate_cv.shutil, "which", lambda binary: f"/usr/bin/{binary}")

    result = pi_validate_cv._cloud_voice_worker_binary_check("python3")

    assert result.status == "pass"
    assert result.details == "/usr/bin/python3"


def test_voice_worker_protocol_close_does_not_wait_for_stop_response() -> None:
    writes: list[str] = []

    class _Stdin:
        def write(self, data: str) -> int:
            writes.append(data)
            return len(data)

        def flush(self) -> None:
            return None

    class _Process:
        stdin = _Stdin()
        returncode: int | None = None
        wait_calls: list[float | None]
        terminated = False
        killed = False

        def __init__(self) -> None:
            self.wait_calls = []

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            self.wait_calls.append(timeout)
            self.returncode = 0
            return 0

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9

    proc = _Process()
    client = pi_validate_cv._VoiceWorkerProtocolClient(["worker"], env={})
    client._proc = proc

    client.close()

    assert "\"type\":\"worker.stop\"" in "".join(writes)
    assert proc.wait_calls == [2.0]
    assert proc.terminated is False
    assert proc.killed is False


def test_cloud_voice_acoustic_loopback_records_and_transcribes_physical_route(
    tmp_path: Path,
    monkeypatch,
) -> None:
    tts_path = tmp_path / "tts-source.wav"
    _write_wav(tts_path)
    popen_calls: list[list[str]] = []

    class FakeClient:
        def request(
            self,
            request_type: str,
            payload: dict[str, object],
            *,
            timeout_seconds: float,
        ) -> dict[str, object]:
            del timeout_seconds
            if request_type == "voice.speak":
                return {
                    "audio_path": str(tts_path),
                    "format": "wav",
                    "sample_rate_hz": 16000,
                    "duration_ms": 1000,
                }
            if request_type == "voice.transcribe":
                assert str(payload["audio_path"]).endswith("acoustic-recording.wav")
                return {"text": "play music", "confidence": 1.0, "is_final": True}
            raise AssertionError(f"unexpected request: {request_type}")

    class FakePopen:
        returncode = 0

        def __init__(self, args: list[str], **_kwargs: object) -> None:
            self.args = args
            popen_calls.append(args)

        def communicate(self, *, timeout: float | None = None) -> tuple[str, str]:
            del timeout
            recorded_path = Path(self.args[-1])
            _write_wav(recorded_path)
            return "", ""

        def kill(self) -> None:
            self.returncode = -9

    monkeypatch.setattr(pi_validate_cv.shutil, "which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr(pi_validate_cv.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(
        "yoyopod.backends.voice.output.AlsaOutputPlayer.play_wav",
        lambda self, audio_path, **_kwargs: audio_path.exists(),
    )

    results = pi_validate_cv._cloud_voice_acoustic_loopback_check(
        FakeClient(),
        settings=pi_validate_cv.VoiceSettings(
            mode="cloud",
            stt_backend="cloud-worker",
            tts_backend="cloud-worker",
            cloud_worker_enabled=True,
            capture_device_id="capture",
            speaker_device_id="playback",
        ),
        phrase="play music",
        artifacts_dir=str(tmp_path / "artifacts"),
    )

    assert [result.status for result in results] == ["pass", "pass", "pass"]
    assert popen_calls[0][:3] == ["/usr/bin/arecord", "-D", "capture"]
    assert "intent=play_music" in results[-1].details
    artifact_run_dir = next((tmp_path / "artifacts").iterdir())
    assert (artifact_run_dir / "tts-playback.wav").exists()
    assert (artifact_run_dir / "acoustic-recording.wav").exists()


def test_cloud_voice_acoustic_loopback_reports_empty_transcript_artifact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    tts_path = tmp_path / "tts-source.wav"
    _write_wav(tts_path)

    class FakeClient:
        def request(
            self,
            request_type: str,
            payload: dict[str, object],
            *,
            timeout_seconds: float,
        ) -> dict[str, object]:
            del payload, timeout_seconds
            if request_type == "voice.speak":
                return {
                    "audio_path": str(tts_path),
                    "format": "wav",
                    "sample_rate_hz": 16000,
                    "duration_ms": 1000,
                }
            if request_type == "voice.transcribe":
                return {"text": "", "confidence": 0.0, "is_final": True}
            raise AssertionError(f"unexpected request: {request_type}")

    class FakePopen:
        returncode = 0

        def __init__(self, args: list[str], **_kwargs: object) -> None:
            self.args = args

        def communicate(self, *, timeout: float | None = None) -> tuple[str, str]:
            del timeout
            _write_wav(Path(self.args[-1]))
            return "", ""

        def kill(self) -> None:
            self.returncode = -9

    monkeypatch.setattr(pi_validate_cv.shutil, "which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr(pi_validate_cv.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(
        "yoyopod.backends.voice.output.AlsaOutputPlayer.play_wav",
        lambda self, audio_path, **_kwargs: audio_path.exists(),
    )

    results = pi_validate_cv._cloud_voice_acoustic_loopback_check(
        FakeClient(),
        settings=pi_validate_cv.VoiceSettings(
            mode="cloud",
            stt_backend="cloud-worker",
            tts_backend="cloud-worker",
            cloud_worker_enabled=True,
            capture_device_id="capture",
            speaker_device_id="playback",
        ),
        phrase="play music",
        artifacts_dir=str(tmp_path / "artifacts"),
    )

    assert [result.name for result in results] == [
        "cloud_voice_acoustic_recording",
        "cloud_voice_acoustic_stt",
    ]
    assert [result.status for result in results] == ["pass", "fail"]
    assert "transcript=''" in results[-1].details
    assert "acoustic-recording.wav" in results[-1].details
