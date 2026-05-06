"""Cloud voice validation subcommand."""

from __future__ import annotations

import math
import os
import queue
import shutil
import subprocess
import threading
import time
import wave
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

import typer
from typing import Annotated

from yoyopod_cli.contracts.worker_protocol import (
    WorkerEnvelope,
    encode_envelope,
    make_envelope,
    parse_envelope_line,
)
from yoyopod_cli.common import REPO_ROOT, configure_logging, resolve_config_dir
from yoyopod_cli.config.models.voice import VoiceConfig
from yoyopod_cli.pi.validate._common import _CheckResult, _print_summary
from yoyopod_cli.pi.validate.service_env import load_service_env_file, resolve_service_env_file


@dataclass(slots=True, frozen=True)
class VoiceSettings:
    """Flattened cloud voice validation settings."""

    mode: str
    stt_backend: str
    tts_backend: str
    speaker_device_id: str | None
    capture_device_id: str | None
    sample_rate_hz: int
    cloud_worker_enabled: bool
    cloud_worker_provider: str
    cloud_worker_request_timeout_seconds: float
    cloud_worker_max_audio_seconds: float
    cloud_worker_stt_model: str
    cloud_worker_stt_language: str
    cloud_worker_tts_model: str
    cloud_worker_tts_voice: str
    cloud_worker_tts_instructions: str


@dataclass(slots=True, frozen=True)
class VoiceWorkerTranscribeResult:
    text: str
    confidence: float


@dataclass(slots=True, frozen=True)
class VoiceWorkerSpeakResult:
    audio_path: Path


def _load_cloud_voice_env_file(env_file: Path) -> list[str]:
    """Load service-style KEY=VALUE assignments into this validation process."""

    return load_service_env_file(env_file)


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


def _voice_settings_from_config(config: VoiceConfig) -> VoiceSettings:
    """Build the small settings projection needed by cloud voice validation."""

    return VoiceSettings(
        mode=config.assistant.mode,
        stt_backend=config.assistant.stt_backend,
        tts_backend=config.assistant.tts_backend,
        speaker_device_id=config.audio.speaker_device_id.strip() or None,
        capture_device_id=config.audio.capture_device_id.strip() or None,
        sample_rate_hz=config.assistant.sample_rate_hz,
        cloud_worker_enabled=config.worker.enabled,
        cloud_worker_provider=config.worker.provider,
        cloud_worker_request_timeout_seconds=config.worker.request_timeout_seconds,
        cloud_worker_max_audio_seconds=config.worker.max_audio_seconds,
        cloud_worker_stt_model=config.worker.stt_model,
        cloud_worker_stt_language=config.worker.stt_language,
        cloud_worker_tts_model=config.worker.tts_model,
        cloud_worker_tts_voice=config.worker.tts_voice,
        cloud_worker_tts_instructions=config.worker.tts_instructions,
    )


def _build_transcribe_payload(
    audio_path: Path,
    *,
    sample_rate_hz: int,
    language: str,
    max_audio_seconds: float,
    model: str,
) -> dict[str, Any]:
    return {
        "audio_path": audio_path.as_posix(),
        "format": "wav",
        "sample_rate_hz": sample_rate_hz,
        "channels": 1,
        "language": language,
        "max_audio_seconds": max_audio_seconds,
        "delete_input_on_success": False,
        "model": model,
    }


def _build_speak_payload(
    *,
    text: str,
    voice: str,
    model: str,
    instructions: str,
    sample_rate_hz: int,
) -> dict[str, Any]:
    return {
        "text": text,
        "voice": voice,
        "model": model,
        "instructions": instructions,
        "format": "wav",
        "sample_rate_hz": sample_rate_hz,
    }


def _parse_transcribe_result(payload: Mapping[str, Any]) -> VoiceWorkerTranscribeResult:
    text = _required_string(payload, "text").strip()
    return VoiceWorkerTranscribeResult(
        text=text,
        confidence=float(payload.get("confidence", 0.0)),
    )


def _parse_speak_result(payload: Mapping[str, Any]) -> VoiceWorkerSpeakResult:
    audio_path = _required_string(payload, "audio_path").strip()
    if not audio_path:
        raise ValueError("audio_path must be a non-empty string")
    return VoiceWorkerSpeakResult(audio_path=Path(audio_path))


def _parse_health_payload(payload: Mapping[str, Any]) -> tuple[bool, str, str]:
    provider = _required_string(payload, "provider").strip()
    if not provider:
        raise ValueError("provider must be a non-empty string")
    return (
        bool(payload.get("healthy", False)),
        provider,
        str(payload.get("message", "")).strip(),
    )


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a non-empty string")
    return value


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


def _cloud_voice_command_match_check(
    transcript: str,
    *,
    config_dir: Path,
    runtime_binary: str,
) -> _CheckResult:
    """Validate that Rust runtime routing maps one cloud STT transcript to a command."""

    preview = " ".join(transcript.strip().split())
    runtime_worker = _resolve_runtime_binary(runtime_binary)
    if not runtime_worker.exists():
        return _CheckResult(
            name="cloud_voice_command_match",
            status="fail",
            details=f"missing Rust runtime binary at {runtime_worker}",
        )

    try:
        completed = subprocess.run(
            [
                str(runtime_worker),
                "--config-dir",
                str(config_dir),
                "--route-voice-transcript",
                transcript,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        return _CheckResult(
            name="cloud_voice_command_match",
            status="fail",
            details=f"transcript={preview!r} runtime_error={exc}",
        )

    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "").strip()
        return _CheckResult(
            name="cloud_voice_command_match",
            status="fail",
            details=f"transcript={preview!r} runtime_rc={completed.returncode} {details}",
        )

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return _CheckResult(
            name="cloud_voice_command_match",
            status="fail",
            details=f"transcript={preview!r} invalid_runtime_json={exc}",
        )

    command = payload.get("command") if isinstance(payload, dict) else None
    kind = str(payload.get("kind", "")) if isinstance(payload, dict) else ""
    if kind != "command" or not isinstance(command, dict):
        return _CheckResult(
            name="cloud_voice_command_match",
            status="fail",
            details=f"transcript={preview!r} kind={kind or 'unknown'} intent=unknown",
        )

    intent = str(command.get("intent", "unknown"))
    return _CheckResult(
        name="cloud_voice_command_match",
        status="pass",
        details=f"transcript={preview!r} runtime={runtime_worker} intent={intent}",
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
            argv = ["device/speech/build/yoyopod-speech-host"]
    argv = [str(arg) for arg in argv if str(arg).strip()]
    if not argv:
        argv = ["device/speech/build/yoyopod-speech-host"]
    path = Path(argv[0])
    if not path.is_absolute():
        if path.parent == Path("."):
            resolved = shutil.which(argv[0])
            if resolved is not None:
                argv[0] = resolved
        else:
            argv[0] = str(REPO_ROOT / path)
    return argv


def _resolve_runtime_binary(runtime_binary: str) -> Path:
    raw = runtime_binary.strip()
    if not raw:
        suffix = ".exe" if os.name == "nt" else ""
        raw = str(Path("device") / "runtime" / "build" / f"yoyopod-runtime{suffix}")

    path = Path(raw)
    if path.is_absolute():
        return path
    if path.parent == Path("."):
        resolved = shutil.which(raw)
        if resolved is not None:
            return Path(resolved)

    for candidate in (
        Path.cwd() / "app" / path,
        Path.cwd() / path,
        REPO_ROOT / "app" / path,
        REPO_ROOT / path,
    ):
        if candidate.exists():
            return candidate
    return REPO_ROOT / path


def _cloud_voice_worker_health_check(
    client: _VoiceWorkerProtocolClient,
    *,
    timeout_seconds: float,
) -> _CheckResult:
    """Validate that the worker/provider accepts health probes."""

    try:
        healthy, provider, message = _parse_health_payload(
            client.request("voice.health", {}, timeout_seconds=timeout_seconds)
        )
    except Exception as exc:
        return _CheckResult(
            name="cloud_voice_worker_health",
            status="fail",
            details=str(exc),
        )
    status = "pass" if healthy else "fail"
    details = f"provider={provider}, healthy={healthy}"
    if message:
        details += f", message={message}"
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


def _play_wav(audio_path: Path, *, device_id: str | None, timeout_seconds: float) -> bool:
    aplay = shutil.which("aplay")
    if aplay is None:
        return False
    candidates = [device_id, "playback", "default", None]
    seen: set[str | None] = set()
    for device in candidates:
        if device in seen:
            continue
        seen.add(device)
        command = [aplay, "-q"]
        if device:
            command.extend(["-D", device])
        command.append(str(audio_path))
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except Exception:
            continue
        if result.returncode == 0:
            return True
    return False


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
    config_dir: Path,
    runtime_binary: str,
    phrase: str,
    artifacts_dir: str,
) -> list[_CheckResult]:
    """Validate the physical speaker->microphone route with cloud STT."""

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
        speak_result = _parse_speak_result(
            client.request(
                "voice.speak",
                _build_speak_payload(
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
        played = _play_wav(
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
            _build_transcribe_payload(
                audio_path=recorded_artifact,
                sample_rate_hz=settings.sample_rate_hz,
                language=settings.cloud_worker_stt_language,
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

        transcript_result = _parse_transcribe_result(transcript_payload)
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
        match_result = _cloud_voice_command_match_check(
            transcript_result.text,
            config_dir=config_dir,
            runtime_binary=runtime_binary,
        )
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
    config_dir: Path,
    runtime_binary: str,
    cycle: int,
    phrase: str,
    playback: bool,
) -> list[_CheckResult]:
    timeout_seconds = max(5.0, settings.cloud_worker_request_timeout_seconds)
    results: list[_CheckResult] = []
    generated_audio: Path | None = None
    try:
        started = time.monotonic()
        speak_payload = _build_speak_payload(
            text=phrase,
            voice=settings.cloud_worker_tts_voice,
            model=settings.cloud_worker_tts_model,
            instructions=settings.cloud_worker_tts_instructions,
            sample_rate_hz=settings.sample_rate_hz,
        )
        speak_result = _parse_speak_result(
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
        transcript_result = _parse_transcribe_result(
            client.request(
                "voice.transcribe",
                _build_transcribe_payload(
                    audio_path=generated_audio,
                    sample_rate_hz=settings.sample_rate_hz,
                    language=settings.cloud_worker_stt_language,
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
        match_result = _cloud_voice_command_match_check(
            transcript_result.text,
            config_dir=config_dir,
            runtime_binary=runtime_binary,
        )
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
            played = _play_wav(
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
    runtime_binary: Annotated[
        str,
        typer.Option(
            "--runtime-binary",
            help="Override the Rust runtime binary used for transcript routing checks.",
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
    """Validate cloud STT/TTS and Rust voice command routing on the target."""
    from loguru import logger

    from yoyopod_cli.config import ConfigManager

    configure_logging(verbose)
    config_path = resolve_config_dir(config_dir)
    env_path = resolve_service_env_file(env_file)

    logger.info("Running target cloud voice validation")

    loaded_env_keys = _load_cloud_voice_env_file(env_path)
    results: list[_CheckResult] = [_cloud_voice_env_file_check(env_path, loaded_env_keys)]

    config_manager = ConfigManager(config_dir=str(config_path))
    settings = _voice_settings_from_config(config_manager.get_voice_settings())
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
                            config_dir=config_path,
                            runtime_binary=runtime_binary,
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
                                config_dir=config_path,
                                runtime_binary=runtime_binary,
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
