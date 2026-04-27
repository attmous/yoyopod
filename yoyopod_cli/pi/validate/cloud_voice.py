"""Cloud voice validation subcommand."""

from __future__ import annotations

import math
import os
import queue
import shlex
import shutil
import subprocess
import threading
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import typer
from typing import Annotated

from yoyopod.core.workers.protocol import (
    WorkerEnvelope,
    encode_envelope,
    make_envelope,
    parse_envelope_line,
)
from yoyopod.integrations.voice import VoiceSettings, match_voice_command
from yoyopod.integrations.voice.worker_contract import (
    build_speak_payload,
    build_transcribe_payload,
    parse_health_result,
    parse_speak_result,
    parse_transcribe_result,
)
from yoyopod_cli.common import REPO_ROOT, configure_logging, resolve_config_dir
from yoyopod_cli.pi.validate._common import _CheckResult, _print_summary


def _load_cloud_voice_env_file(env_file: Path) -> list[str]:
    """Load service-style KEY=VALUE assignments into this validation process."""

    if not env_file.exists():
        return []

    loaded: list[str] = []
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            parts = shlex.split(line, comments=True, posix=True)
        except ValueError:
            continue
        if not parts:
            continue
        if parts[0] == "export":
            parts = parts[1:]
        if not parts or "=" not in parts[0]:
            continue
        key, value = parts[0].split("=", 1)
        key = key.strip()
        if not key:
            continue
        os.environ[key] = value
        loaded.append(key)
    return loaded


def _cloud_voice_env_file_check(env_file: Path, loaded_keys: list[str]) -> _CheckResult:
    """Report which service environment keys were imported without exposing values."""

    if env_file.exists():
        loaded = ", ".join(loaded_keys) if loaded_keys else "none"
        return _CheckResult(
            name="cloud_voice_env",
            status="pass",
            details=f"env_file={env_file} loaded={loaded}",
        )
    return _CheckResult(
        name="cloud_voice_env",
        status="warn",
        details=f"env_file={env_file} not found; using current process environment",
    )


def _cloud_voice_settings_check(settings: VoiceSettings, *, provider: str) -> _CheckResult:
    """Validate that cloud-worker voice settings are active."""

    failures: list[str] = []
    if settings.mode != "cloud":
        failures.append(f"mode={settings.mode}")
    if settings.stt_backend != "cloud-worker":
        failures.append(f"stt_backend={settings.stt_backend}")
    if settings.tts_backend != "cloud-worker":
        failures.append(f"tts_backend={settings.tts_backend}")
    if not settings.cloud_worker_enabled:
        failures.append("cloud_worker_enabled=false")
    if provider == "openai" and not os.environ.get("OPENAI_API_KEY", "").strip():
        failures.append("OPENAI_API_KEY=missing")

    details = (
        f"mode={settings.mode}, stt={settings.stt_backend}, tts={settings.tts_backend}, "
        f"provider={provider}, speaker={settings.speaker_device_id or 'auto'}, "
        f"capture={settings.capture_device_id or 'auto'}"
    )
    if provider == "openai":
        details += ", OPENAI_API_KEY=set" if os.environ.get("OPENAI_API_KEY") else ""
    if failures:
        return _CheckResult(
            name="cloud_voice_settings",
            status="fail",
            details=f"{details}; invalid: {', '.join(failures)}",
        )
    return _CheckResult(name="cloud_voice_settings", status="pass", details=details)


def _cloud_voice_command_match_check(transcript: str) -> _CheckResult:
    """Validate that one cloud STT transcript maps to a supported local command."""

    command = match_voice_command(transcript)
    preview = " ".join(transcript.strip().split())
    if not command.is_command:
        return _CheckResult(
            name="cloud_voice_command_match",
            status="fail",
            details=f"transcript={preview!r} intent=unknown",
        )
    return _CheckResult(
        name="cloud_voice_command_match",
        status="pass",
        details=f"transcript={preview!r} intent={command.intent.value}",
    )


class _VoiceWorkerProtocolClient:
    """Small synchronous worker-protocol client for Pi validation."""

    def __init__(self, worker_argv: list[str] | Path, *, env: dict[str, str]) -> None:
        if isinstance(worker_argv, Path):
            worker_argv = [str(worker_argv)]
        if not worker_argv:
            raise ValueError("voice worker argv must not be empty")
        self.worker_argv = [str(arg) for arg in worker_argv]
        self.binary_path = Path(self.worker_argv[0])
        self.env = env
        self._proc: subprocess.Popen[str] | None = None
        self._stdout_lines: queue.Queue[str] = queue.Queue()
        self._stderr_tail_lines: list[str] = []
        self._stderr_lock = threading.Lock()

    def __enter__(self) -> "_VoiceWorkerProtocolClient":
        self.start()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def start(self) -> None:
        self._proc = subprocess.Popen(
            self.worker_argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=self.env,
            bufsize=1,
        )
        assert self._proc.stdout is not None
        assert self._proc.stderr is not None
        threading.Thread(
            target=self._read_stdout,
            args=(self._proc.stdout,),
            daemon=True,
            name="CloudVoiceValidateStdout",
        ).start()
        threading.Thread(
            target=self._read_stderr,
            args=(self._proc.stderr,),
            daemon=True,
            name="CloudVoiceValidateStderr",
        ).start()
        self._wait_for_ready(timeout_seconds=5.0)

    def close(self) -> None:
        proc = self._proc
        if proc is None:
            return
        if proc.poll() is None:
            try:
                self._write_command(
                    "worker.stop",
                    {},
                    request_id=f"cloud-voice-stop-{uuid4().hex}",
                    deadline_ms=1000,
                )
                proc.wait(timeout=2.0)
            except Exception:
                pass
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
        self._proc = None

    def request(
        self,
        request_type: str,
        payload: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        request_id = f"cloud-voice-validate-{uuid4().hex}"
        self._write_command(
            request_type,
            payload,
            request_id=request_id,
            deadline_ms=max(1, int(timeout_seconds * 1000)),
        )
        deadline = time.monotonic() + timeout_seconds + 2.0
        while time.monotonic() < deadline:
            envelope = self._read_envelope(timeout_seconds=max(0.01, deadline - time.monotonic()))
            if envelope.request_id != request_id:
                continue
            if envelope.kind == "error" or envelope.type == "voice.error":
                message = envelope.payload.get("message", "worker error")
                raise RuntimeError(str(message))
            return envelope.payload
        raise TimeoutError(f"voice worker request timed out: {request_type}")

    def _write_command(
        self,
        request_type: str,
        payload: dict[str, Any],
        *,
        request_id: str,
        deadline_ms: int,
    ) -> None:
        proc = self._require_process()
        assert proc.stdin is not None
        proc.stdin.write(
            encode_envelope(
                make_envelope(
                    kind="command",
                    type=request_type,
                    request_id=request_id,
                    deadline_ms=deadline_ms,
                    payload=payload,
                )
            )
        )
        proc.stdin.flush()

    def _wait_for_ready(self, *, timeout_seconds: float) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            envelope = self._read_envelope(timeout_seconds=max(0.01, deadline - time.monotonic()))
            if envelope.type == "voice.ready":
                return
        raise TimeoutError("voice worker did not emit voice.ready")

    def _read_envelope(self, *, timeout_seconds: float) -> WorkerEnvelope:
        try:
            line = self._stdout_lines.get(timeout=timeout_seconds)
        except queue.Empty as exc:
            proc = self._proc
            proc_state = "not_started"
            if proc is not None:
                proc_state = (
                    f"exited rc={proc.returncode}" if proc.poll() is not None else "running"
                )
            raise TimeoutError(
                "voice worker produced no protocol envelope "
                f"within {timeout_seconds:.1f}s ({proc_state}); stderr={self._stderr_tail()}"
            ) from exc
        return parse_envelope_line(line)

    def _read_stdout(self, stdout: Any) -> None:
        for line in stdout:
            self._stdout_lines.put(line)

    def _read_stderr(self, stderr: Any) -> None:
        for line in stderr:
            stripped = line.strip()
            if not stripped:
                continue
            with self._stderr_lock:
                self._stderr_tail_lines.append(stripped)
                del self._stderr_tail_lines[:-20]

    def _stderr_tail(self) -> str:
        with self._stderr_lock:
            if not self._stderr_tail_lines:
                return "<empty>"
            return " | ".join(self._stderr_tail_lines[-5:])

    def _require_process(self) -> subprocess.Popen[str]:
        if self._proc is None:
            raise RuntimeError("voice worker process is not started")
        if self._proc.poll() is not None:
            raise RuntimeError(f"voice worker exited rc={self._proc.returncode}")
        return self._proc


def _cloud_voice_worker_binary_check(binary_path: Path | str) -> _CheckResult:
    binary_text = str(binary_path)
    path = Path(binary_text)
    if not path.is_absolute() and path.parent == Path("."):
        resolved = shutil.which(binary_text)
        if resolved is None:
            return _CheckResult(
                name="cloud_voice_worker_binary",
                status="fail",
                details=f"missing executable {binary_text}",
            )
        return _CheckResult(
            name="cloud_voice_worker_binary",
            status="pass",
            details=resolved,
        )
    if not path.exists():
        return _CheckResult(
            name="cloud_voice_worker_binary",
            status="fail",
            details=f"missing {path}",
        )
    if not os.access(path, os.X_OK):
        return _CheckResult(
            name="cloud_voice_worker_binary",
            status="fail",
            details=f"not executable {path}",
        )
    return _CheckResult(
        name="cloud_voice_worker_binary",
        status="pass",
        details=str(path),
    )


def _resolve_cloud_voice_worker_binary(
    config_manager: Any,
    worker_binary: str,
) -> Path:
    """Resolve the configured voice worker binary path for target validation."""

    return Path(_resolve_cloud_voice_worker_argv(config_manager, worker_binary)[0])


def _resolve_cloud_voice_worker_argv(
    config_manager: Any,
    worker_binary: str,
) -> list[str]:
    """Resolve the full configured voice worker argv for target validation."""

    argv: list[str]
    if worker_binary.strip():
        argv = [worker_binary.strip()]
    else:
        argv = []
        try:
            voice_config = config_manager.get_voice_settings()
            argv = list(getattr(getattr(voice_config, "worker", None), "argv", []) or [])
        except Exception:
            argv = []
        if not argv:
            argv = ["workers/voice/go/build/yoyopod-voice-worker"]
    argv = [str(arg) for arg in argv if str(arg).strip()]
    if not argv:
        argv = ["workers/voice/go/build/yoyopod-voice-worker"]
    path = Path(argv[0])
    if not path.is_absolute():
        if path.parent == Path("."):
            resolved = shutil.which(argv[0])
            if resolved is not None:
                argv[0] = resolved
        else:
            argv[0] = str(REPO_ROOT / path)
    return argv


def _cloud_voice_worker_health_check(
    client: _VoiceWorkerProtocolClient,
    *,
    timeout_seconds: float,
) -> _CheckResult:
    """Validate that the worker/provider accepts health probes."""

    try:
        health = parse_health_result(
            client.request("voice.health", {}, timeout_seconds=timeout_seconds)
        )
    except Exception as exc:
        return _CheckResult(
            name="cloud_voice_worker_health",
            status="fail",
            details=str(exc),
        )
    status = "pass" if health.healthy else "fail"
    details = f"provider={health.provider}, healthy={health.healthy}"
    if health.message:
        details += f", message={health.message}"
    return _CheckResult(name="cloud_voice_worker_health", status=status, details=details)


def _cloud_voice_capture_route_check(settings: VoiceSettings) -> _CheckResult:
    arecord = shutil.which("arecord")
    if arecord is None:
        return _CheckResult(
            name="cloud_voice_capture_route",
            status="fail",
            details="arecord not found",
        )
    device = settings.capture_device_id or "default"
    command = [
        arecord,
        "-D",
        device,
        "-t",
        "raw",
        "-f",
        "S16_LE",
        "-r",
        str(settings.sample_rate_hz),
        "-c",
        "1",
        "-d",
        "1",
        "-q",
        os.devnull,
    ]
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except Exception as exc:
        return _CheckResult(
            name="cloud_voice_capture_route",
            status="fail",
            details=f"device={device} error={exc}",
        )
    elapsed_ms = (time.monotonic() - started) * 1000
    if result.returncode != 0:
        return _CheckResult(
            name="cloud_voice_capture_route",
            status="fail",
            details=f"device={device} rc={result.returncode} stderr={result.stderr.strip()}",
        )
    return _CheckResult(
        name="cloud_voice_capture_route",
        status="pass",
        details=f"device={device} elapsed_ms={elapsed_ms:.1f}",
    )


def _wav_duration_seconds(audio_path: Path) -> float | None:
    try:
        with wave.open(str(audio_path), "rb") as handle:
            frame_rate = handle.getframerate()
            if frame_rate <= 0:
                return None
            return handle.getnframes() / float(frame_rate)
    except (EOFError, OSError, wave.Error):
        return None


def _cloud_voice_artifact_run_dir(artifacts_dir: str) -> Path:
    """Return a timestamped artifact directory for one cloud voice validation run."""

    root = Path(artifacts_dir)
    if not root.is_absolute():
        root = REPO_ROOT / root
    run_label = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return root / f"cloud-voice-{run_label}"


def _cloud_voice_acoustic_loopback_check(
    client: _VoiceWorkerProtocolClient,
    *,
    settings: VoiceSettings,
    phrase: str,
    artifacts_dir: str,
) -> list[_CheckResult]:
    """Validate the physical speaker->microphone route with cloud STT."""

    from yoyopod.backends.voice.output import AlsaOutputPlayer

    arecord = shutil.which("arecord")
    if arecord is None:
        return [
            _CheckResult(
                name="cloud_voice_acoustic_loopback",
                status="fail",
                details="arecord not found",
            )
        ]

    timeout_seconds = max(5.0, settings.cloud_worker_request_timeout_seconds)
    run_dir = _cloud_voice_artifact_run_dir(artifacts_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    tts_artifact = run_dir / "tts-playback.wav"
    recorded_artifact = run_dir / "acoustic-recording.wav"
    generated_audio: Path | None = None

    try:
        started = time.monotonic()
        speak_result = parse_speak_result(
            client.request(
                "voice.speak",
                build_speak_payload(
                    text=phrase,
                    voice=settings.cloud_worker_tts_voice,
                    model=settings.cloud_worker_tts_model,
                    instructions=settings.cloud_worker_tts_instructions,
                    sample_rate_hz=settings.sample_rate_hz,
                ),
                timeout_seconds=timeout_seconds,
            )
        )
        generated_audio = speak_result.audio_path
        shutil.copy2(generated_audio, tts_artifact)
        duration = _wav_duration_seconds(generated_audio) or 1.0
        capture_seconds = max(2, min(8, math.ceil(duration + 1.5)))
        device = settings.capture_device_id or "default"
        command = [
            arecord,
            "-D",
            device,
            "-t",
            "wav",
            "-f",
            "S16_LE",
            "-r",
            str(settings.sample_rate_hz),
            "-c",
            "1",
            "-d",
            str(capture_seconds),
            "-q",
            str(recorded_artifact),
        ]
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(0.25)
        played = AlsaOutputPlayer().play_wav(
            generated_audio,
            device_id=settings.speaker_device_id,
            timeout_seconds=max(4.0, duration + 2.0),
        )
        try:
            _stdout, stderr = proc.communicate(timeout=capture_seconds + 2.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            _stdout, stderr = proc.communicate(timeout=2.0)
            return [
                _CheckResult(
                    name="cloud_voice_acoustic_recording",
                    status="fail",
                    details=f"device={device} timed out artifact_dir={run_dir}",
                )
            ]

        if proc.returncode != 0:
            return [
                _CheckResult(
                    name="cloud_voice_acoustic_recording",
                    status="fail",
                    details=(
                        f"device={device} rc={proc.returncode} "
                        f"stderr={stderr.strip()} artifact_dir={run_dir}"
                    ),
                )
            ]
        byte_count = recorded_artifact.stat().st_size if recorded_artifact.exists() else 0
        if not played or byte_count <= 44:
            return [
                _CheckResult(
                    name="cloud_voice_acoustic_recording",
                    status="fail",
                    details=(
                        f"device={device} played={played} bytes={byte_count} "
                        f"artifact_dir={run_dir}"
                    ),
                )
            ]

        results = [
            _CheckResult(
                name="cloud_voice_acoustic_recording",
                status="pass",
                details=(
                    f"device={device} speaker={settings.speaker_device_id or 'default'} "
                    f"played={played} bytes={byte_count} capture_seconds={capture_seconds} "
                    f"elapsed_ms={(time.monotonic() - started) * 1000:.1f} "
                    f"artifact_dir={run_dir}"
                ),
            )
        ]

        started = time.monotonic()
        transcript_payload = client.request(
            "voice.transcribe",
            build_transcribe_payload(
                audio_path=recorded_artifact,
                sample_rate_hz=settings.sample_rate_hz,
                language="en",
                max_audio_seconds=settings.cloud_worker_max_audio_seconds,
                model=settings.cloud_worker_stt_model,
            ),
            timeout_seconds=timeout_seconds,
        )
        transcript_text = str(transcript_payload.get("text", "")).strip()
        if not transcript_text:
            results.append(
                _CheckResult(
                    name="cloud_voice_acoustic_stt",
                    status="fail",
                    details=(
                        "transcript='' confidence="
                        f"{float(transcript_payload.get('confidence', 0.0))} "
                        f"elapsed_ms={(time.monotonic() - started) * 1000:.1f} "
                        f"artifact={recorded_artifact}"
                    ),
                )
            )
            return results

        transcript_result = parse_transcribe_result(transcript_payload)
        results.append(
            _CheckResult(
                name="cloud_voice_acoustic_stt",
                status="pass",
                details=(
                    f"transcript={transcript_result.text!r} "
                    f"confidence={transcript_result.confidence} "
                    f"elapsed_ms={(time.monotonic() - started) * 1000:.1f} "
                    f"artifact={recorded_artifact}"
                ),
            )
        )
        match_result = _cloud_voice_command_match_check(transcript_result.text)
        results.append(
            _CheckResult(
                name="cloud_voice_acoustic_command_match",
                status=match_result.status,
                details=match_result.details,
            )
        )
        return results
    except Exception as exc:
        return [
            _CheckResult(
                name="cloud_voice_acoustic_loopback",
                status="fail",
                details=f"{exc} artifact_dir={run_dir}",
            )
        ]
    finally:
        if generated_audio is not None:
            generated_audio.unlink(missing_ok=True)


def _cloud_voice_cycle_check(
    client: _VoiceWorkerProtocolClient,
    *,
    settings: VoiceSettings,
    cycle: int,
    phrase: str,
    playback: bool,
) -> list[_CheckResult]:
    from yoyopod.backends.voice.output import AlsaOutputPlayer

    timeout_seconds = max(5.0, settings.cloud_worker_request_timeout_seconds)
    results: list[_CheckResult] = []
    generated_audio: Path | None = None
    try:
        started = time.monotonic()
        speak_payload = build_speak_payload(
            text=phrase,
            voice=settings.cloud_worker_tts_voice,
            model=settings.cloud_worker_tts_model,
            instructions=settings.cloud_worker_tts_instructions,
            sample_rate_hz=settings.sample_rate_hz,
        )
        speak_result = parse_speak_result(
            client.request("voice.speak", speak_payload, timeout_seconds=timeout_seconds)
        )
        generated_audio = speak_result.audio_path
        duration = _wav_duration_seconds(generated_audio)
        byte_count = generated_audio.stat().st_size if generated_audio.exists() else -1
        results.append(
            _CheckResult(
                name=f"cloud_voice_tts_cycle_{cycle}",
                status="pass",
                details=(
                    f"audio={generated_audio} bytes={byte_count} "
                    f"duration_s={duration:.2f} elapsed_ms={(time.monotonic() - started) * 1000:.1f}"
                    if duration is not None
                    else f"audio={generated_audio} bytes={byte_count}"
                ),
            )
        )

        started = time.monotonic()
        transcript_result = parse_transcribe_result(
            client.request(
                "voice.transcribe",
                build_transcribe_payload(
                    audio_path=generated_audio,
                    sample_rate_hz=settings.sample_rate_hz,
                    language="en",
                    max_audio_seconds=settings.cloud_worker_max_audio_seconds,
                    model=settings.cloud_worker_stt_model,
                ),
                timeout_seconds=timeout_seconds,
            )
        )
        results.append(
            _CheckResult(
                name=f"cloud_voice_stt_cycle_{cycle}",
                status="pass",
                details=(
                    f"transcript={transcript_result.text!r} confidence={transcript_result.confidence} "
                    f"elapsed_ms={(time.monotonic() - started) * 1000:.1f}"
                ),
            )
        )
        match_result = _cloud_voice_command_match_check(transcript_result.text)
        results.append(
            _CheckResult(
                name=f"{match_result.name}_cycle_{cycle}",
                status=match_result.status,
                details=match_result.details,
            )
        )
        if match_result.status == "fail":
            return results

        if playback:
            started = time.monotonic()
            duration = duration or 0.0
            played = AlsaOutputPlayer().play_wav(
                generated_audio,
                device_id=settings.speaker_device_id,
                timeout_seconds=max(4.0, min(20.0, duration + 2.0)),
            )
            results.append(
                _CheckResult(
                    name=f"cloud_voice_playback_cycle_{cycle}",
                    status="pass" if played else "fail",
                    details=(
                        f"device={settings.speaker_device_id or 'default'} "
                        f"played={played} elapsed_ms={(time.monotonic() - started) * 1000:.1f}"
                    ),
                )
            )
    except Exception as exc:
        results.append(
            _CheckResult(
                name=f"cloud_voice_cycle_{cycle}",
                status="fail",
                details=str(exc),
            )
        )
    finally:
        if generated_audio is not None:
            generated_audio.unlink(missing_ok=True)
    return results


def cloud_voice(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    env_file: Annotated[
        str,
        typer.Option(
            "--env-file",
            help="Service EnvironmentFile to load before resolving cloud voice settings.",
        ),
    ] = "/etc/default/yoyopod-dev",
    worker_binary: Annotated[
        str,
        typer.Option(
            "--worker-binary",
            help="Override the configured voice worker binary path.",
        ),
    ] = "",
    provider: Annotated[
        str,
        typer.Option(
            "--provider",
            help="Override YOYOPOD_VOICE_WORKER_PROVIDER for this validation run.",
        ),
    ] = "",
    cycles: Annotated[
        int,
        typer.Option("--cycles", help="How many TTS -> STT -> command cycles to run."),
    ] = 2,
    phrase: Annotated[
        str,
        typer.Option("--phrase", help="Known command phrase to synthesize and transcribe."),
    ] = "play music",
    playback: Annotated[
        bool,
        typer.Option(
            "--playback/--no-playback",
            help="Play generated TTS WAV through the configured ALSA speaker route.",
        ),
    ] = True,
    capture_route: Annotated[
        bool,
        typer.Option(
            "--capture-route/--no-capture-route",
            help="Validate the configured ALSA capture route with arecord.",
        ),
    ] = True,
    acoustic_loopback: Annotated[
        bool,
        typer.Option(
            "--acoustic-loopback/--no-acoustic-loopback",
            help=(
                "Play generated speech through the speaker, record it through the mic, "
                "then transcribe that recorded WAV."
            ),
        ),
    ] = True,
    artifacts_dir: Annotated[
        str,
        typer.Option(
            "--artifacts-dir",
            help="Directory for cloud voice validation audio artifacts.",
        ),
    ] = "logs/validation/cloud-voice",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Validate cloud STT/TTS and local voice command routing on the target."""
    from loguru import logger

    from yoyopod.config import ConfigManager
    from yoyopod.integrations.voice.settings import VoiceSettingsResolver

    configure_logging(verbose)
    config_path = resolve_config_dir(config_dir)
    env_path = Path(env_file)
    if not env_path.is_absolute():
        env_path = REPO_ROOT / env_path

    logger.info("Running target cloud voice validation")

    loaded_env_keys = _load_cloud_voice_env_file(env_path)
    results: list[_CheckResult] = [_cloud_voice_env_file_check(env_path, loaded_env_keys)]

    config_manager = ConfigManager(config_dir=str(config_path))
    settings = VoiceSettingsResolver(
        context=None,
        config_manager=config_manager,
    ).defaults()
    selected_provider = (
        provider.strip()
        or settings.cloud_worker_provider
        or os.environ.get("YOYOPOD_VOICE_WORKER_PROVIDER", "")
        or "mock"
    ).lower()
    if provider.strip():
        os.environ["YOYOPOD_VOICE_WORKER_PROVIDER"] = selected_provider

    worker_argv = _resolve_cloud_voice_worker_argv(config_manager, worker_binary)
    binary_path = Path(worker_argv[0])
    results.extend(
        [
            _cloud_voice_settings_check(settings, provider=selected_provider),
            _cloud_voice_worker_binary_check(binary_path),
        ]
    )
    if capture_route:
        results.append(_cloud_voice_capture_route_check(settings))

    if not any(result.status == "fail" for result in results):
        worker_env = dict(os.environ)
        worker_env["YOYOPOD_VOICE_WORKER_PROVIDER"] = selected_provider
        timeout_seconds = max(5.0, settings.cloud_worker_request_timeout_seconds)
        try:
            with _VoiceWorkerProtocolClient(worker_argv, env=worker_env) as client:
                health_result = _cloud_voice_worker_health_check(
                    client,
                    timeout_seconds=timeout_seconds,
                )
                results.append(health_result)
                if health_result.status != "fail":
                    for cycle in range(1, max(1, cycles) + 1):
                        cycle_results = _cloud_voice_cycle_check(
                            client,
                            settings=settings,
                            cycle=cycle,
                            phrase=phrase,
                            playback=playback,
                        )
                        results.extend(cycle_results)
                        if any(result.status == "fail" for result in cycle_results):
                            break
                    if acoustic_loopback and not any(result.status == "fail" for result in results):
                        results.extend(
                            _cloud_voice_acoustic_loopback_check(
                                client,
                                settings=settings,
                                phrase=phrase,
                                artifacts_dir=artifacts_dir,
                            )
                        )
        except Exception as exc:
            results.append(
                _CheckResult(
                    name="cloud_voice_worker_protocol",
                    status="fail",
                    details=str(exc),
                )
            )

    _print_summary("cloud-voice", results)
    if any(result.status == "fail" for result in results):
        raise typer.Exit(code=1)
