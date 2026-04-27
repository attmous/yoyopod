# Go Cloud Voice Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a supervised Go cloud voice worker that can handle cloud STT/TTS requests without blocking the YoYoPod supervisor UI loop.

**Architecture:** The Python supervisor remains the owner of UI, app state, command execution, audio capture, playback, local non-speech feedback, and degraded-state presentation. The Go worker runs behind the existing NDJSON worker protocol, starts in fake-provider mode for deterministic tests, and then gains one concrete OpenAI Audio API provider for STT/TTS. Python voice code gets a worker client and cloud STT/TTS backends that preserve the existing `VoiceManager` boundary while ensuring worker sends/results are applied on the main thread.

**Tech Stack:** Python 3.12, Go 1.22+, stdlib `net/http`, NDJSON over stdio, existing `WorkerSupervisor`, `Bus`, `MainThreadScheduler`, OpenAI Audio API (`/v1/audio/transcriptions`, `/v1/audio/speech`), `uv`, pytest, `go test`.

---

## Scope Check

This plan implements Phase 2 only: the Go cloud voice worker. It does not implement the Phase 3 Python network worker, does not move capture/playback into Go, and does not create a VoIP sidecar.

The first mergeable slice must work without cloud credentials. The fake provider is required so CI, local development, and review can validate the worker contract before the OpenAI provider is enabled on hardware.

References used for provider details:

- OpenAI Speech to Text guide: <https://platform.openai.com/docs/guides/speech-to-text>
- OpenAI Text to Speech guide: <https://platform.openai.com/docs/guides/text-to-speech>
- OpenAI Audio API reference: <https://platform.openai.com/docs/api-reference/audio>

---

## File Structure

Create:

- `yoyopod/integrations/voice/worker_contract.py`
  - Defines Python-side payload/result dataclasses for `voice.transcribe`, `voice.speak`, worker errors, and degraded events.
  - Validates envelopes before app code consumes them.

- `yoyopod/integrations/voice/worker_client.py`
  - Owns pending voice worker requests.
  - Schedules `WorkerSupervisor.send_request()` onto the main thread.
  - Receives `WorkerMessageReceivedEvent` on the bus and resolves waiting background-thread calls.
  - Keeps request waiting out of the UI loop.

- `yoyopod/backends/voice/cloud_worker.py`
  - Implements `SpeechToTextBackend` and `TextToSpeechBackend` adapters backed by `VoiceWorkerClient`.
  - Keeps the existing `VoiceManager` composition point intact.

- `tests/integrations/voice/test_worker_contract.py`
  - Contract parsing and validation tests.

- `tests/integrations/voice/test_worker_client.py`
  - Main-thread scheduling, result correlation, timeout, and error tests.

- `tests/backends/voice/test_cloud_worker.py`
  - STT/TTS backend tests using a fake `VoiceWorkerClient`.

- `workers/voice/go/go.mod`
  - Standalone Go module for the worker.

- `workers/voice/go/cmd/yoyopod-voice-worker/main.go`
  - Worker process entrypoint.

- `workers/voice/go/internal/protocol/protocol.go`
  - Envelope structs, JSON parsing, and encoding.

- `workers/voice/go/internal/worker/worker.go`
  - Command dispatch, active request tracking, cancellation, and deadline handling.

- `workers/voice/go/internal/provider/provider.go`
  - Provider interface and typed provider request/result structs.

- `workers/voice/go/internal/provider/mock.go`
  - Deterministic fake provider for tests and local simulation.

- `workers/voice/go/internal/provider/openai.go`
  - OpenAI provider implementation using stdlib HTTP.

- `workers/voice/go/internal/worker/worker_test.go`
  - Go tests for fake provider, deadlines, cancellation, and busy behavior.

- `workers/voice/go/internal/provider/openai_test.go`
  - Go tests using `httptest.Server` for STT/TTS request construction and error mapping.

- `tests/core/test_go_voice_worker_contract.py`
  - Python integration tests that run `go run` when Go is available and skip cleanly otherwise.

Modify:

- `yoyopod/config/models/voice.py`
  - Add cloud voice worker config.

- `config/voice/assistant.yaml`
  - Add authored defaults for cloud mode, worker path, OpenAI model names, timeouts, and local fallback policy.

- `tests/config/test_config_models.py`
  - Cover new typed config defaults and env overrides.

- `yoyopod/core/application.py`
  - Add `voice_worker_client` field.

- `yoyopod/core/bootstrap/components_boot.py`
  - Register/start the voice worker when cloud mode is enabled.

- `yoyopod/core/bootstrap/screens_boot.py`
  - Build `VoiceManager` with cloud worker STT/TTS backends when configured.

- `yoyopod/integrations/voice/runtime.py`
  - Move spoken outcome playback off the main thread so cloud TTS cannot block the UI loop.

- `yoyopod/integrations/voice/models.py`
  - Add voice mode and cloud-worker fields to `VoiceSettings`.

- `yoyopod/integrations/voice/settings.py`
  - Resolve new config fields into `VoiceSettings`.

- `docs/PI_PROFILING_WORKFLOW.md`
  - Add the Phase 2 RAM and responsiveness measurement procedure.

- `yoyopod_cli/build.py`
  - Add an explicit Go voice worker build helper.

---

## Task 1: Add Cloud Voice Configuration

**Files:**

- Modify: `yoyopod/config/models/voice.py`
- Modify: `config/voice/assistant.yaml`
- Modify: `tests/config/test_config_models.py`

- [ ] **Step 1: Add failing config defaults test**

Add this to `tests/config/test_config_models.py`:

```python
def test_voice_config_includes_cloud_worker_defaults(tmp_path, monkeypatch) -> None:
    """Cloud voice settings should have safe defaults without requiring credentials."""

    for key in [
        "YOYOPOD_VOICE_MODE",
        "YOYOPOD_VOICE_WORKER_ENABLED",
        "YOYOPOD_VOICE_WORKER_PROVIDER",
        "YOYOPOD_VOICE_WORKER_ARGV",
        "YOYOPOD_CLOUD_STT_MODEL",
        "YOYOPOD_CLOUD_TTS_MODEL",
        "YOYOPOD_CLOUD_TTS_VOICE",
    ]:
        monkeypatch.delenv(key, raising=False)

    config_file = tmp_path / "voice" / "assistant.yaml"
    settings = load_config_model_from_yaml(VoiceConfig, config_file)

    assert settings.assistant.mode == "local"
    assert settings.worker.enabled is False
    assert settings.worker.domain == "voice"
    assert settings.worker.provider == "mock"
    assert settings.worker.argv == ["workers/voice/go/build/yoyopod-voice-worker"]
    assert settings.worker.request_timeout_seconds == 12.0
    assert settings.worker.max_audio_seconds == 30.0
    assert settings.worker.stt_model == "gpt-4o-mini-transcribe"
    assert settings.worker.tts_model == "gpt-4o-mini-tts"
    assert settings.worker.tts_voice == "alloy"
    assert settings.worker.local_feedback_enabled is True
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
uv run pytest -q tests/config/test_config_models.py::test_voice_config_includes_cloud_worker_defaults
```

Expected: fails because `VoiceConfig` has no `worker` field and `VoiceAssistantConfig` has no `mode`.

- [ ] **Step 3: Implement typed config**

In `yoyopod/config/models/voice.py`, replace the file with this content:

```python
"""Voice assistant and device configuration models."""

from __future__ import annotations

from dataclasses import dataclass, field

from yoyopod.config.models.core import config_value


@dataclass(slots=True)
class VoiceAssistantConfig:
    """Voice-command and spoken-response policy."""

    mode: str = config_value(default="local", env="YOYOPOD_VOICE_MODE")
    commands_enabled: bool = config_value(default=True, env="YOYOPOD_VOICE_COMMANDS_ENABLED")
    ai_requests_enabled: bool = config_value(default=True, env="YOYOPOD_AI_REQUESTS_ENABLED")
    screen_read_enabled: bool = config_value(default=False, env="YOYOPOD_SCREEN_READ_ENABLED")
    stt_enabled: bool = config_value(default=True, env="YOYOPOD_STT_ENABLED")
    tts_enabled: bool = config_value(default=True, env="YOYOPOD_TTS_ENABLED")
    stt_backend: str = config_value(default="vosk", env="YOYOPOD_STT_BACKEND")
    tts_backend: str = config_value(default="espeak-ng", env="YOYOPOD_TTS_BACKEND")
    vosk_model_path: str = config_value(
        default="models/vosk-model-small-en-us",
        env="YOYOPOD_VOSK_MODEL_PATH",
    )
    vosk_model_keep_loaded: bool = config_value(
        default=True,
        env="YOYOPOD_VOSK_MODEL_KEEP_LOADED",
    )
    record_seconds: int = config_value(default=4, env="YOYOPOD_VOICE_RECORD_SECONDS")
    sample_rate_hz: int = config_value(default=16000, env="YOYOPOD_VOICE_SAMPLE_RATE_HZ")
    tts_rate_wpm: int = config_value(default=155, env="YOYOPOD_TTS_RATE_WPM")
    tts_voice: str = config_value(default="en", env="YOYOPOD_TTS_VOICE")


@dataclass(slots=True)
class VoiceWorkerConfig:
    """Cloud voice worker process and provider settings."""

    enabled: bool = config_value(default=False, env="YOYOPOD_VOICE_WORKER_ENABLED")
    domain: str = config_value(default="voice", env="YOYOPOD_VOICE_WORKER_DOMAIN")
    provider: str = config_value(default="mock", env="YOYOPOD_VOICE_WORKER_PROVIDER")
    argv: list[str] = config_value(
        default_factory=lambda: ["workers/voice/go/build/yoyopod-voice-worker"],
        env="YOYOPOD_VOICE_WORKER_ARGV",
    )
    request_timeout_seconds: float = config_value(
        default=12.0,
        env="YOYOPOD_VOICE_WORKER_TIMEOUT_SECONDS",
    )
    max_audio_seconds: float = config_value(
        default=30.0,
        env="YOYOPOD_VOICE_WORKER_MAX_AUDIO_SECONDS",
    )
    stt_model: str = config_value(
        default="gpt-4o-mini-transcribe",
        env="YOYOPOD_CLOUD_STT_MODEL",
    )
    tts_model: str = config_value(
        default="gpt-4o-mini-tts",
        env="YOYOPOD_CLOUD_TTS_MODEL",
    )
    tts_voice: str = config_value(default="alloy", env="YOYOPOD_CLOUD_TTS_VOICE")
    tts_instructions: str = config_value(
        default="Speak clearly and briefly for a small handheld device.",
        env="YOYOPOD_CLOUD_TTS_INSTRUCTIONS",
    )
    local_feedback_enabled: bool = config_value(
        default=True,
        env="YOYOPOD_VOICE_LOCAL_FEEDBACK_ENABLED",
    )


@dataclass(slots=True)
class VoiceAudioConfig:
    """Device-owned ALSA selectors consumed by the local voice domain."""

    speaker_device_id: str = config_value(default="", env="YOYOPOD_VOICE_SPEAKER_DEVICE")
    capture_device_id: str = config_value(default="", env="YOYOPOD_VOICE_CAPTURE_DEVICE")


@dataclass(slots=True)
class VoiceConfig:
    """Composed voice domain config built from voice and device layers."""

    assistant: VoiceAssistantConfig = config_value(default_factory=VoiceAssistantConfig)
    audio: VoiceAudioConfig = config_value(default_factory=VoiceAudioConfig)
    worker: VoiceWorkerConfig = config_value(default_factory=VoiceWorkerConfig)
```

- [ ] **Step 4: Export `VoiceWorkerConfig`**

In `yoyopod/config/models/__init__.py`, add `VoiceWorkerConfig` to the import list from `voice.py` and to `__all__`.

In `yoyopod/config/__init__.py`, add `VoiceWorkerConfig` to the import list and to `__all__`.

- [ ] **Step 5: Add authored YAML defaults**

Update `config/voice/assistant.yaml` to:

```yaml
# Local and cloud voice policy.

assistant:
  mode: "local"
  commands_enabled: true
  ai_requests_enabled: true
  screen_read_enabled: false
  stt_enabled: true
  tts_enabled: true
  stt_backend: "vosk"
  tts_backend: "espeak-ng"
  vosk_model_path: "models/vosk-model-small-en-us"
  vosk_model_keep_loaded: true
  record_seconds: 4
  sample_rate_hz: 16000
  tts_rate_wpm: 155
  tts_voice: "en"

worker:
  enabled: false
  domain: "voice"
  provider: "mock"
  argv:
    - "workers/voice/go/build/yoyopod-voice-worker"
  request_timeout_seconds: 12.0
  max_audio_seconds: 30.0
  stt_model: "gpt-4o-mini-transcribe"
  tts_model: "gpt-4o-mini-tts"
  tts_voice: "alloy"
  tts_instructions: "Speak clearly and briefly for a small handheld device."
  local_feedback_enabled: true
```

- [ ] **Step 6: Run config tests**

Run:

```bash
uv run pytest -q tests/config/test_config_models.py
```

Expected: pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add yoyopod/config/models/voice.py yoyopod/config/models/__init__.py yoyopod/config/__init__.py config/voice/assistant.yaml tests/config/test_config_models.py
git commit -m "feat: add cloud voice worker config"
```

---

## Task 2: Add Python Voice Worker Contract

**Files:**

- Create: `yoyopod/integrations/voice/worker_contract.py`
- Modify: `yoyopod/integrations/voice/__init__.py`
- Test: `tests/integrations/voice/test_worker_contract.py`

- [ ] **Step 1: Add contract tests**

Create `tests/integrations/voice/test_worker_contract.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from yoyopod.integrations.voice.worker_contract import (
    VoiceWorkerError,
    VoiceWorkerSpeakResult,
    VoiceWorkerTranscribeResult,
    build_speak_payload,
    build_transcribe_payload,
    parse_speak_result,
    parse_transcribe_result,
    parse_worker_error,
)


def test_build_transcribe_payload_uses_file_metadata() -> None:
    payload = build_transcribe_payload(
        audio_path=Path("/tmp/input.wav"),
        sample_rate_hz=16000,
        language="en",
        max_audio_seconds=30.0,
    )

    assert payload == {
        "audio_path": "/tmp/input.wav",
        "format": "wav",
        "sample_rate_hz": 16000,
        "channels": 1,
        "language": "en",
        "max_audio_seconds": 30.0,
        "delete_input_on_success": False,
    }


def test_parse_transcribe_result_rejects_missing_text() -> None:
    with pytest.raises(ValueError, match="text"):
        parse_transcribe_result({"confidence": 0.4})


def test_parse_transcribe_result_normalizes_values() -> None:
    result = parse_transcribe_result(
        {
            "text": " play music ",
            "confidence": 0.92,
            "is_final": True,
            "provider_latency_ms": 481,
            "audio_duration_ms": 2100,
        }
    )

    assert result == VoiceWorkerTranscribeResult(
        text="play music",
        confidence=0.92,
        is_final=True,
        provider_latency_ms=481,
        audio_duration_ms=2100,
    )


def test_build_speak_payload_includes_provider_options() -> None:
    payload = build_speak_payload(
        text="Playing music",
        voice="alloy",
        model="gpt-4o-mini-tts",
        instructions="Speak clearly.",
        sample_rate_hz=16000,
    )

    assert payload == {
        "text": "Playing music",
        "voice": "alloy",
        "model": "gpt-4o-mini-tts",
        "instructions": "Speak clearly.",
        "format": "wav",
        "sample_rate_hz": 16000,
    }


def test_parse_speak_result_requires_audio_path() -> None:
    with pytest.raises(ValueError, match="audio_path"):
        parse_speak_result({"duration_ms": 10})


def test_parse_speak_result_normalizes_path() -> None:
    result = parse_speak_result(
        {
            "audio_path": "/tmp/output.wav",
            "format": "wav",
            "sample_rate_hz": 16000,
            "duration_ms": 830,
            "provider_latency_ms": 352,
        }
    )

    assert result == VoiceWorkerSpeakResult(
        audio_path=Path("/tmp/output.wav"),
        format="wav",
        sample_rate_hz=16000,
        duration_ms=830,
        provider_latency_ms=352,
    )


def test_parse_worker_error_preserves_retryable_code() -> None:
    error = parse_worker_error(
        {
            "code": "provider_unavailable",
            "message": "provider down",
            "retryable": True,
        }
    )

    assert error == VoiceWorkerError(
        code="provider_unavailable",
        message="provider down",
        retryable=True,
    )
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
uv run pytest -q tests/integrations/voice/test_worker_contract.py
```

Expected: import failure because `worker_contract.py` does not exist.

- [ ] **Step 3: Implement contract module**

Create `yoyopod/integrations/voice/worker_contract.py`:

```python
"""Typed payload helpers for the cloud voice worker protocol."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class VoiceWorkerTranscribeResult:
    text: str
    confidence: float
    is_final: bool
    provider_latency_ms: int | None = None
    audio_duration_ms: int | None = None


@dataclass(frozen=True, slots=True)
class VoiceWorkerSpeakResult:
    audio_path: Path
    format: str
    sample_rate_hz: int
    duration_ms: int | None = None
    provider_latency_ms: int | None = None


@dataclass(frozen=True, slots=True)
class VoiceWorkerError:
    code: str
    message: str
    retryable: bool = False


def build_transcribe_payload(
    *,
    audio_path: Path,
    sample_rate_hz: int,
    language: str,
    max_audio_seconds: float,
) -> dict[str, object]:
    return {
        "audio_path": str(audio_path),
        "format": "wav",
        "sample_rate_hz": int(sample_rate_hz),
        "channels": 1,
        "language": language,
        "max_audio_seconds": float(max_audio_seconds),
        "delete_input_on_success": False,
    }


def build_speak_payload(
    *,
    text: str,
    voice: str,
    model: str,
    instructions: str,
    sample_rate_hz: int,
) -> dict[str, object]:
    return {
        "text": text,
        "voice": voice,
        "model": model,
        "instructions": instructions,
        "format": "wav",
        "sample_rate_hz": int(sample_rate_hz),
    }


def parse_transcribe_result(payload: dict[str, Any]) -> VoiceWorkerTranscribeResult:
    text = _required_str(payload, "text").strip()
    return VoiceWorkerTranscribeResult(
        text=text,
        confidence=float(payload.get("confidence", 0.0)),
        is_final=bool(payload.get("is_final", True)),
        provider_latency_ms=_optional_int(payload.get("provider_latency_ms")),
        audio_duration_ms=_optional_int(payload.get("audio_duration_ms")),
    )


def parse_speak_result(payload: dict[str, Any]) -> VoiceWorkerSpeakResult:
    audio_path = Path(_required_str(payload, "audio_path"))
    return VoiceWorkerSpeakResult(
        audio_path=audio_path,
        format=str(payload.get("format", "wav")),
        sample_rate_hz=int(payload.get("sample_rate_hz", 16000)),
        duration_ms=_optional_int(payload.get("duration_ms")),
        provider_latency_ms=_optional_int(payload.get("provider_latency_ms")),
    )


def parse_worker_error(payload: dict[str, Any]) -> VoiceWorkerError:
    return VoiceWorkerError(
        code=_required_str(payload, "code"),
        message=_required_str(payload, "message"),
        retryable=bool(payload.get("retryable", False)),
    )


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"voice worker payload missing {key!r}")
    return value


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)
```

- [ ] **Step 4: Export contract types**

In `yoyopod/integrations/voice/__init__.py`, export:

```python
from yoyopod.integrations.voice.worker_contract import (
    VoiceWorkerError,
    VoiceWorkerSpeakResult,
    VoiceWorkerTranscribeResult,
    build_speak_payload,
    build_transcribe_payload,
    parse_speak_result,
    parse_transcribe_result,
    parse_worker_error,
)
```

Add the same names to `__all__`.

- [ ] **Step 5: Run tests**

Run:

```bash
uv run pytest -q tests/integrations/voice/test_worker_contract.py
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add yoyopod/integrations/voice/worker_contract.py yoyopod/integrations/voice/__init__.py tests/integrations/voice/test_worker_contract.py
git commit -m "feat: define cloud voice worker contract"
```

---

## Task 3: Add Main-Thread Voice Worker Client

**Files:**

- Create: `yoyopod/integrations/voice/worker_client.py`
- Modify: `yoyopod/integrations/voice/__init__.py`
- Test: `tests/integrations/voice/test_worker_client.py`

- [ ] **Step 1: Add client tests**

Create `tests/integrations/voice/test_worker_client.py`:

```python
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from yoyopod.core.events import WorkerMessageReceivedEvent
from yoyopod.integrations.voice.worker_client import VoiceWorkerClient, VoiceWorkerTimeout


class _Scheduler:
    def __init__(self) -> None:
        self.callbacks: list[object] = []

    def run_on_main(self, callback) -> None:
        self.callbacks.append(callback)

    def drain(self) -> None:
        callbacks = list(self.callbacks)
        self.callbacks.clear()
        for callback in callbacks:
            callback()


class _Supervisor:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def send_request(self, domain: str, **kwargs) -> bool:
        self.requests.append({"domain": domain, **kwargs})
        return True


def test_transcribe_schedules_worker_request_and_resolves_result(tmp_path) -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        domain="voice",
        request_timeout_seconds=1.0,
    )
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"RIFF")
    result_holder: list[object] = []

    thread = threading.Thread(
        target=lambda: result_holder.append(
            client.transcribe(
                audio_path=audio_path,
                sample_rate_hz=16000,
                language="en",
                max_audio_seconds=30.0,
            )
        )
    )
    thread.start()
    scheduler.drain()

    request = supervisor.requests[0]
    assert request["domain"] == "voice"
    assert request["type"] == "voice.transcribe"
    assert request["request_id"]

    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="result",
            type="voice.transcribe.result",
            request_id=str(request["request_id"]),
            payload={"text": "play music", "confidence": 0.9, "is_final": True},
        )
    )
    thread.join(timeout=1.0)

    assert result_holder[0].text == "play music"


def test_worker_error_raises_runtime_error(tmp_path) -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        domain="voice",
        request_timeout_seconds=1.0,
    )
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"RIFF")
    error_holder: list[Exception] = []

    thread = threading.Thread(
        target=lambda: _capture_error(
            error_holder,
            lambda: client.transcribe(
                audio_path=audio_path,
                sample_rate_hz=16000,
                language="en",
                max_audio_seconds=30.0,
            ),
        )
    )
    thread.start()
    scheduler.drain()
    request_id = str(supervisor.requests[0]["request_id"])

    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="error",
            type="voice.error",
            request_id=request_id,
            payload={
                "code": "provider_unavailable",
                "message": "provider down",
                "retryable": True,
            },
        )
    )
    thread.join(timeout=1.0)

    assert "provider_unavailable" in str(error_holder[0])


def test_transcribe_times_out_when_no_result(tmp_path) -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        domain="voice",
        request_timeout_seconds=0.01,
    )
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"RIFF")

    with pytest.raises(VoiceWorkerTimeout):
        client.transcribe(
            audio_path=audio_path,
            sample_rate_hz=16000,
            language="en",
            max_audio_seconds=30.0,
        )


def test_ignores_messages_from_other_worker_domain() -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        domain="voice",
        request_timeout_seconds=1.0,
    )

    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="network",
            kind="result",
            type="voice.transcribe.result",
            request_id="req-1",
            payload={"text": "ignored"},
        )
    )

    assert client.pending_count == 0


def _capture_error(errors: list[Exception], callback) -> None:
    try:
        callback()
    except Exception as exc:
        errors.append(exc)
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
uv run pytest -q tests/integrations/voice/test_worker_client.py
```

Expected: import failure because `worker_client.py` does not exist.

- [ ] **Step 3: Implement worker client**

Create `yoyopod/integrations/voice/worker_client.py`:

```python
"""Main-thread-safe client for supervised voice worker requests."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from yoyopod.core.events import WorkerMessageReceivedEvent
from yoyopod.integrations.voice.worker_contract import (
    VoiceWorkerSpeakResult,
    VoiceWorkerTranscribeResult,
    build_speak_payload,
    build_transcribe_payload,
    parse_speak_result,
    parse_transcribe_result,
    parse_worker_error,
)

if TYPE_CHECKING:
    from yoyopod.core.scheduler import MainThreadScheduler
    from yoyopod.core.workers.supervisor import WorkerSupervisor


class VoiceWorkerTimeout(TimeoutError):
    """Raised when the voice worker misses the caller deadline."""


class VoiceWorkerUnavailable(RuntimeError):
    """Raised when the voice worker cannot accept or complete a request."""


@dataclass(slots=True)
class _PendingVoiceRequest:
    request_id: str
    expected_type: str
    completed: threading.Event
    result: object | None = None
    error: Exception | None = None


class VoiceWorkerClient:
    """Send voice requests through WorkerSupervisor without blocking the UI thread."""

    def __init__(
        self,
        *,
        scheduler: "MainThreadScheduler",
        worker_supervisor: "WorkerSupervisor",
        domain: str,
        request_timeout_seconds: float,
    ) -> None:
        self._scheduler = scheduler
        self._worker_supervisor = worker_supervisor
        self._domain = domain
        self._request_timeout_seconds = max(0.1, float(request_timeout_seconds))
        self._lock = threading.Lock()
        self._pending: dict[str, _PendingVoiceRequest] = {}

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def transcribe(
        self,
        *,
        audio_path: Path,
        sample_rate_hz: int,
        language: str,
        max_audio_seconds: float,
    ) -> VoiceWorkerTranscribeResult:
        payload = build_transcribe_payload(
            audio_path=audio_path,
            sample_rate_hz=sample_rate_hz,
            language=language,
            max_audio_seconds=max_audio_seconds,
        )
        pending = self._send(
            type="voice.transcribe",
            payload=payload,
            expected_type="voice.transcribe.result",
        )
        return self._wait_for(pending, result_type=VoiceWorkerTranscribeResult)

    def speak(
        self,
        *,
        text: str,
        voice: str,
        model: str,
        instructions: str,
        sample_rate_hz: int,
    ) -> VoiceWorkerSpeakResult:
        payload = build_speak_payload(
            text=text,
            voice=voice,
            model=model,
            instructions=instructions,
            sample_rate_hz=sample_rate_hz,
        )
        pending = self._send(
            type="voice.speak",
            payload=payload,
            expected_type="voice.speak.result",
        )
        return self._wait_for(pending, result_type=VoiceWorkerSpeakResult)

    def handle_worker_message(self, event: WorkerMessageReceivedEvent) -> None:
        if event.domain != self._domain or event.request_id is None:
            return
        with self._lock:
            pending = self._pending.get(event.request_id)
        if pending is None:
            return

        try:
            if event.kind == "error" or event.type == "voice.error":
                worker_error = parse_worker_error(event.payload)
                pending.error = VoiceWorkerUnavailable(
                    f"{worker_error.code}: {worker_error.message}"
                )
            elif event.type == "voice.transcribe.result":
                pending.result = parse_transcribe_result(event.payload)
            elif event.type == "voice.speak.result":
                pending.result = parse_speak_result(event.payload)
            elif event.type == "voice.cancelled":
                pending.error = VoiceWorkerUnavailable("cancelled")
            else:
                return
        except Exception as exc:
            pending.error = exc
        finally:
            pending.completed.set()

    def _send(
        self,
        *,
        type: str,
        payload: dict[str, object],
        expected_type: str,
    ) -> _PendingVoiceRequest:
        request_id = f"voice-{uuid.uuid4().hex}"
        pending = _PendingVoiceRequest(
            request_id=request_id,
            expected_type=expected_type,
            completed=threading.Event(),
        )
        with self._lock:
            self._pending[request_id] = pending

        def send_on_main() -> None:
            sent = self._worker_supervisor.send_request(
                self._domain,
                type=type,
                payload=payload,
                request_id=request_id,
                timeout_seconds=self._request_timeout_seconds,
            )
            if not sent:
                pending.error = VoiceWorkerUnavailable("voice worker unavailable")
                pending.completed.set()

        self._scheduler.run_on_main(send_on_main)
        return pending

    def _wait_for(self, pending: _PendingVoiceRequest, *, result_type: type[object]):
        if not pending.completed.wait(self._request_timeout_seconds + 0.25):
            with self._lock:
                self._pending.pop(pending.request_id, None)
            raise VoiceWorkerTimeout(f"voice worker timed out: {pending.request_id}")
        with self._lock:
            self._pending.pop(pending.request_id, None)
        if pending.error is not None:
            raise pending.error
        if not isinstance(pending.result, result_type):
            raise VoiceWorkerUnavailable(f"voice worker returned no {pending.expected_type}")
        return pending.result
```

- [ ] **Step 4: Export client**

In `yoyopod/integrations/voice/__init__.py`, export `VoiceWorkerClient`, `VoiceWorkerTimeout`, and `VoiceWorkerUnavailable`.

- [ ] **Step 5: Run tests**

Run:

```bash
uv run pytest -q tests/integrations/voice/test_worker_client.py
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add yoyopod/integrations/voice/worker_client.py yoyopod/integrations/voice/__init__.py tests/integrations/voice/test_worker_client.py
git commit -m "feat: add voice worker client"
```

---

## Task 4: Add Cloud Worker STT/TTS Backends

**Files:**

- Create: `yoyopod/backends/voice/cloud_worker.py`
- Modify: `yoyopod/backends/voice/__init__.py`
- Test: `tests/backends/voice/test_cloud_worker.py`

- [ ] **Step 1: Add backend tests**

Create `tests/backends/voice/test_cloud_worker.py`:

```python
from __future__ import annotations

from pathlib import Path

from yoyopod.backends.voice.cloud_worker import (
    CloudWorkerSpeechToTextBackend,
    CloudWorkerTextToSpeechBackend,
)
from yoyopod.integrations.voice.models import VoiceSettings, VoiceTranscript
from yoyopod.integrations.voice.worker_contract import (
    VoiceWorkerSpeakResult,
    VoiceWorkerTranscribeResult,
)


class _Client:
    def __init__(self) -> None:
        self.transcribe_calls: list[dict[str, object]] = []
        self.speak_calls: list[dict[str, object]] = []

    def transcribe(self, **kwargs) -> VoiceWorkerTranscribeResult:
        self.transcribe_calls.append(kwargs)
        return VoiceWorkerTranscribeResult(text="play music", confidence=0.9, is_final=True)

    def speak(self, **kwargs) -> VoiceWorkerSpeakResult:
        self.speak_calls.append(kwargs)
        return VoiceWorkerSpeakResult(
            audio_path=Path("/tmp/cloud-tts.wav"),
            format="wav",
            sample_rate_hz=16000,
        )


def test_cloud_stt_available_only_for_cloud_backend() -> None:
    client = _Client()
    backend = CloudWorkerSpeechToTextBackend(client=client)

    assert backend.is_available(VoiceSettings(stt_backend="cloud-worker")) is True
    assert backend.is_available(VoiceSettings(stt_backend="vosk")) is False


def test_cloud_stt_transcribes_through_client(tmp_path: Path) -> None:
    client = _Client()
    backend = CloudWorkerSpeechToTextBackend(client=client)
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"RIFF")

    transcript = backend.transcribe(
        audio_path,
        VoiceSettings(
            stt_backend="cloud-worker",
            sample_rate_hz=16000,
            cloud_worker_max_audio_seconds=30.0,
        ),
    )

    assert transcript == VoiceTranscript(text="play music", confidence=0.9, is_final=True)
    assert client.transcribe_calls[0]["audio_path"] == audio_path


def test_cloud_tts_available_only_for_cloud_backend() -> None:
    client = _Client()
    backend = CloudWorkerTextToSpeechBackend(client=client)

    assert backend.is_available(VoiceSettings(tts_backend="cloud-worker")) is True
    assert backend.is_available(VoiceSettings(tts_backend="espeak-ng")) is False


def test_cloud_tts_renders_and_plays_returned_file(monkeypatch) -> None:
    client = _Client()
    played_paths: list[Path] = []
    backend = CloudWorkerTextToSpeechBackend(
        client=client,
        play_wav=lambda path, **_kwargs: played_paths.append(path) or True,
    )

    assert backend.speak(
        "Playing music",
        VoiceSettings(
            tts_backend="cloud-worker",
            cloud_worker_tts_model="gpt-4o-mini-tts",
            cloud_worker_tts_voice="alloy",
            cloud_worker_tts_instructions="Speak clearly.",
            sample_rate_hz=16000,
        ),
    )

    assert client.speak_calls[0]["text"] == "Playing music"
    assert played_paths == [Path("/tmp/cloud-tts.wav")]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest -q tests/backends/voice/test_cloud_worker.py
```

Expected: import failure because `cloud_worker.py` does not exist and `VoiceSettings` lacks cloud fields.

- [ ] **Step 3: Extend `VoiceSettings`**

In `yoyopod/integrations/voice/models.py`, add fields to `VoiceSettings`:

```python
    mode: str = "local"
    cloud_worker_enabled: bool = False
    cloud_worker_domain: str = "voice"
    cloud_worker_provider: str = "mock"
    cloud_worker_request_timeout_seconds: float = 12.0
    cloud_worker_max_audio_seconds: float = 30.0
    cloud_worker_stt_model: str = "gpt-4o-mini-transcribe"
    cloud_worker_tts_model: str = "gpt-4o-mini-tts"
    cloud_worker_tts_voice: str = "alloy"
    cloud_worker_tts_instructions: str = (
        "Speak clearly and briefly for a small handheld device."
    )
    local_feedback_enabled: bool = True
```

- [ ] **Step 4: Implement cloud backends**

Create `yoyopod/backends/voice/cloud_worker.py`:

```python
"""Voice STT/TTS backends backed by the supervised cloud voice worker."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol

from loguru import logger

from yoyopod.backends.voice.output import AlsaOutputPlayer
from yoyopod.integrations.voice.models import VoiceSettings, VoiceTranscript
from yoyopod.integrations.voice.worker_contract import (
    VoiceWorkerSpeakResult,
    VoiceWorkerTranscribeResult,
)


class _VoiceWorkerClient(Protocol):
    def transcribe(self, **kwargs) -> VoiceWorkerTranscribeResult:
        """Return a cloud transcription."""

    def speak(self, **kwargs) -> VoiceWorkerSpeakResult:
        """Return a rendered speech audio file."""


class CloudWorkerSpeechToTextBackend:
    """Speech-to-text adapter that delegates to the Go voice worker."""

    def __init__(self, *, client: _VoiceWorkerClient) -> None:
        self._client = client

    def is_available(self, settings: VoiceSettings) -> bool:
        return bool(settings.stt_enabled and settings.stt_backend == "cloud-worker")

    def transcribe(self, audio_path: Path, settings: VoiceSettings) -> VoiceTranscript:
        if not self.is_available(settings):
            return VoiceTranscript(text="", confidence=0.0, is_final=True)
        result = self._client.transcribe(
            audio_path=audio_path,
            sample_rate_hz=settings.sample_rate_hz,
            language="en",
            max_audio_seconds=settings.cloud_worker_max_audio_seconds,
        )
        return VoiceTranscript(
            text=result.text,
            confidence=result.confidence,
            is_final=result.is_final,
        )


class CloudWorkerTextToSpeechBackend:
    """Text-to-speech adapter that delegates rendering to the Go voice worker."""

    def __init__(
        self,
        *,
        client: _VoiceWorkerClient,
        play_wav: Callable[..., bool] | None = None,
    ) -> None:
        self._client = client
        self._play_wav = play_wav or AlsaOutputPlayer().play_wav

    def is_available(self, settings: VoiceSettings) -> bool:
        return bool(settings.tts_enabled and settings.tts_backend == "cloud-worker")

    def speak(self, text: str, settings: VoiceSettings) -> bool:
        if not text.strip() or not self.is_available(settings):
            return False
        try:
            result = self._client.speak(
                text=text,
                voice=settings.cloud_worker_tts_voice,
                model=settings.cloud_worker_tts_model,
                instructions=settings.cloud_worker_tts_instructions,
                sample_rate_hz=settings.sample_rate_hz,
            )
            play_kwargs: dict[str, object] = {"timeout_seconds": 10.0}
            if settings.speaker_device_id:
                play_kwargs["device_id"] = settings.speaker_device_id
            return bool(self._play_wav(result.audio_path, **play_kwargs))
        except Exception as exc:
            logger.warning("Cloud voice TTS failed: {}", exc)
            return False
```

- [ ] **Step 5: Export backends**

In `yoyopod/backends/voice/__init__.py`, export `CloudWorkerSpeechToTextBackend` and `CloudWorkerTextToSpeechBackend`.

- [ ] **Step 6: Run backend tests**

Run:

```bash
uv run pytest -q tests/backends/voice/test_cloud_worker.py
```

Expected: pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add yoyopod/integrations/voice/models.py yoyopod/backends/voice/cloud_worker.py yoyopod/backends/voice/__init__.py tests/backends/voice/test_cloud_worker.py
git commit -m "feat: add cloud worker voice backends"
```

---

## Task 5: Wire Cloud Backends Into Voice Runtime Without Blocking TTS

**Files:**

- Modify: `yoyopod/core/application.py`
- Modify: `yoyopod/core/bootstrap/components_boot.py`
- Modify: `yoyopod/core/bootstrap/screens_boot.py`
- Modify: `yoyopod/integrations/voice/runtime.py`
- Modify: `yoyopod/integrations/voice/settings.py`
- Test: `tests/core/test_bootstrap.py`
- Test: `tests/integrations/voice/test_runtime.py`

- [ ] **Step 1: Add bootstrap test**

Add this test to `tests/core/test_bootstrap.py`:

```python
def test_bootstrap_registers_voice_worker_when_cloud_mode_enabled(monkeypatch, tmp_path) -> None:
    app = YoyoPodApp(simulate=True)
    app.config_manager = ConfigManager(config_dir=str(tmp_path))
    app.bus = Bus()
    app.scheduler = MainThreadScheduler()
    app.worker_supervisor = WorkerSupervisor(scheduler=app.scheduler, bus=app.bus)
    registered: list[tuple[str, object]] = []
    started: list[str] = []
    monkeypatch.setattr(app.worker_supervisor, "register", lambda domain, config: registered.append((domain, config)))
    monkeypatch.setattr(app.worker_supervisor, "start", lambda domain: started.append(domain) or True)
    voice_file = tmp_path / "voice" / "assistant.yaml"
    voice_file.parent.mkdir(parents=True, exist_ok=True)
    voice_file.write_text(
        """
assistant:
  mode: cloud
  stt_backend: cloud-worker
  tts_backend: cloud-worker
worker:
  enabled: true
  argv:
    - python
    - fake_worker.py
""".strip(),
        encoding="utf-8",
    )
    app.config_manager.load_voice_config()

    ComponentsBoot(app, logger=logger).setup_voice_worker()

    assert registered[0][0] == "voice"
    assert started == ["voice"]
    assert app.voice_worker_client is not None
```

- [ ] **Step 2: Add non-blocking TTS runtime test**

Add this test to `tests/integrations/voice/test_runtime.py`:

```python
def test_voice_outcome_speaks_on_background_thread() -> None:
    started = threading.Event()
    release = threading.Event()

    class _VoiceService:
        def speak(self, _text: str) -> bool:
            started.set()
            release.wait(timeout=2.0)
            return True

    runtime = VoiceRuntimeCoordinator(
        context=None,
        settings_resolver=_SettingsResolver(),
        command_executor=_CommandExecutor(),
        voice_service_factory=lambda _settings: _VoiceService(),
    )

    runtime._apply_outcome(
        VoiceCommandOutcome("Done", "Playing music", should_speak=True)
    )

    assert started.wait(timeout=1.0)
    release.set()
```

Define `_SettingsResolver` and `_CommandExecutor` in that test module if they do not already exist:

```python
class _SettingsResolver:
    def defaults(self) -> VoiceSettings:
        return VoiceSettings()

    def current(self) -> VoiceSettings:
        return VoiceSettings()


class _CommandExecutor:
    def execute(self, _transcript: str) -> VoiceCommandOutcome:
        return VoiceCommandOutcome("Done", "OK", should_speak=False)
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
uv run pytest -q tests/core/test_bootstrap.py::test_bootstrap_registers_voice_worker_when_cloud_mode_enabled tests/integrations/voice/test_runtime.py::test_voice_outcome_speaks_on_background_thread
```

Expected: bootstrap test fails because `setup_voice_worker()` and `voice_worker_client` do not exist; runtime test fails because `speak()` is still synchronous.

- [ ] **Step 4: Add app field**

In `yoyopod/core/application.py`, import `VoiceWorkerClient` under normal imports and add this field in `YoyoPodApp.__init__()`:

```python
self.voice_worker_client: VoiceWorkerClient | None = None
```

- [ ] **Step 5: Add component boot helper**

In `yoyopod/core/bootstrap/components_boot.py`, add imports:

```python
from yoyopod.core.events import WorkerMessageReceivedEvent
from yoyopod.core.workers import WorkerProcessConfig
from yoyopod.integrations.voice import VoiceWorkerClient
```

Add method on `ComponentsBoot`:

```python
def setup_voice_worker(self) -> bool:
    """Register and start the cloud voice worker when configured."""

    if self.app.config_manager is None:
        return False
    voice_cfg = self.app.config_manager.get_voice_settings()
    if voice_cfg.assistant.mode != "cloud" or not voice_cfg.worker.enabled:
        return False
    if self.app.voice_worker_client is None:
        self.app.voice_worker_client = VoiceWorkerClient(
            scheduler=self.app.scheduler,
            worker_supervisor=self.app.worker_supervisor,
            domain=voice_cfg.worker.domain,
            request_timeout_seconds=voice_cfg.worker.request_timeout_seconds,
        )
        self.app.bus.subscribe(
            WorkerMessageReceivedEvent,
            self.app.voice_worker_client.handle_worker_message,
        )
    self.app.worker_supervisor.register(
        voice_cfg.worker.domain,
        WorkerProcessConfig(
            name="voice",
            argv=list(voice_cfg.worker.argv),
            cwd=None,
            env=None,
        ),
    )
    return self.app.worker_supervisor.start(voice_cfg.worker.domain)
```

Call `self.setup_voice_worker()` from `initialize_core_components()` after voice config is loaded and before screen setup.

- [ ] **Step 6: Build cloud-aware `VoiceManager` factory**

In `yoyopod/core/bootstrap/screens_boot.py`, import:

```python
from yoyopod.backends.voice import (
    CloudWorkerSpeechToTextBackend,
    CloudWorkerTextToSpeechBackend,
)
from yoyopod.integrations.voice import VoiceManager
```

Before constructing `VoiceRuntimeCoordinator`, add:

```python
voice_service_factory = None
if (
    voice_cfg is not None
    and voice_cfg.assistant.mode == "cloud"
    and self.app.voice_worker_client is not None
):
    def voice_service_factory(settings: VoiceSettings) -> VoiceManager:
        return VoiceManager(
            settings=settings,
            stt_backend=CloudWorkerSpeechToTextBackend(
                client=self.app.voice_worker_client,
            ),
            tts_backend=CloudWorkerTextToSpeechBackend(
                client=self.app.voice_worker_client,
            ),
        )
```

Pass `voice_service_factory=voice_service_factory` into `VoiceRuntimeCoordinator`.

- [ ] **Step 7: Populate cloud fields in `VoiceSettings`**

In the `VoiceSettings(...)` constructor in `screens_boot.py`, include:

```python
mode=voice_cfg.assistant.mode if voice_cfg is not None else "local",
cloud_worker_enabled=voice_cfg.worker.enabled if voice_cfg is not None else False,
cloud_worker_domain=voice_cfg.worker.domain if voice_cfg is not None else "voice",
cloud_worker_provider=voice_cfg.worker.provider if voice_cfg is not None else "mock",
cloud_worker_request_timeout_seconds=(
    voice_cfg.worker.request_timeout_seconds if voice_cfg is not None else 12.0
),
cloud_worker_max_audio_seconds=(
    voice_cfg.worker.max_audio_seconds if voice_cfg is not None else 30.0
),
cloud_worker_stt_model=voice_cfg.worker.stt_model if voice_cfg is not None else "gpt-4o-mini-transcribe",
cloud_worker_tts_model=voice_cfg.worker.tts_model if voice_cfg is not None else "gpt-4o-mini-tts",
cloud_worker_tts_voice=voice_cfg.worker.tts_voice if voice_cfg is not None else "alloy",
cloud_worker_tts_instructions=(
    voice_cfg.worker.tts_instructions
    if voice_cfg is not None
    else "Speak clearly and briefly for a small handheld device."
),
local_feedback_enabled=(
    voice_cfg.worker.local_feedback_enabled if voice_cfg is not None else True
),
```

- [ ] **Step 8: Move spoken outcome playback to a background thread**

In `yoyopod/integrations/voice/runtime.py`, replace:

```python
if outcome.should_speak and not self._voice_service().speak(outcome.body):
    logger.debug("Voice response not spoken: {}", outcome.body)
```

with:

```python
if outcome.should_speak:
    self._speak_outcome_async(outcome.body)
```

Add method:

```python
def _speak_outcome_async(self, text: str) -> None:
    """Speak an outcome outside the main-thread UI path."""

    def run() -> None:
        if not self._voice_service().speak(text):
            logger.debug("Voice response not spoken: {}", text)

    threading.Thread(
        target=run,
        daemon=True,
        name="VoiceRuntimeTTS",
    ).start()
```

- [ ] **Step 9: Run focused tests**

Run:

```bash
uv run pytest -q tests/core/test_bootstrap.py::test_bootstrap_registers_voice_worker_when_cloud_mode_enabled tests/integrations/voice/test_runtime.py::test_voice_outcome_speaks_on_background_thread tests/backends/voice/test_cloud_worker.py tests/integrations/voice/test_worker_client.py
```

Expected: pass.

- [ ] **Step 10: Commit**

Run:

```bash
git add yoyopod/core/application.py yoyopod/core/bootstrap/components_boot.py yoyopod/core/bootstrap/screens_boot.py yoyopod/integrations/voice/runtime.py yoyopod/integrations/voice/settings.py tests/core/test_bootstrap.py tests/integrations/voice/test_runtime.py
git commit -m "feat: wire cloud voice worker into runtime"
```

---

## Task 6: Add Go Worker Protocol and Fake Provider

**Files:**

- Create: `workers/voice/go/go.mod`
- Create: `workers/voice/go/cmd/yoyopod-voice-worker/main.go`
- Create: `workers/voice/go/internal/protocol/protocol.go`
- Create: `workers/voice/go/internal/provider/provider.go`
- Create: `workers/voice/go/internal/provider/mock.go`
- Create: `workers/voice/go/internal/worker/worker.go`
- Create: `workers/voice/go/internal/worker/worker_test.go`

- [ ] **Step 1: Add Go module**

Create `workers/voice/go/go.mod`:

```go
module github.com/moustafattia/yoyopod-core/workers/voice/go

go 1.22
```

- [ ] **Step 2: Add protocol package**

Create `workers/voice/go/internal/protocol/protocol.go`:

```go
package protocol

import (
	"encoding/json"
	"fmt"
)

const SchemaVersion = 1

type Envelope struct {
	SchemaVersion int                    `json:"schema_version"`
	Kind          string                 `json:"kind"`
	Type          string                 `json:"type"`
	RequestID     *string                `json:"request_id"`
	TimestampMS   int64                  `json:"timestamp_ms"`
	DeadlineMS    int64                  `json:"deadline_ms"`
	Payload       map[string]interface{} `json:"payload"`
}

func Decode(line []byte) (Envelope, error) {
	var envelope Envelope
	if err := json.Unmarshal(line, &envelope); err != nil {
		return Envelope{}, err
	}
	if envelope.SchemaVersion != SchemaVersion {
		return Envelope{}, fmt.Errorf("unsupported schema_version %d", envelope.SchemaVersion)
	}
	if envelope.Payload == nil {
		envelope.Payload = map[string]interface{}{}
	}
	return envelope, nil
}

func Encode(envelope Envelope) ([]byte, error) {
	if envelope.SchemaVersion == 0 {
		envelope.SchemaVersion = SchemaVersion
	}
	if envelope.Payload == nil {
		envelope.Payload = map[string]interface{}{}
	}
	return json.Marshal(envelope)
}
```

- [ ] **Step 3: Add provider interface and mock provider**

Create `workers/voice/go/internal/provider/provider.go`:

```go
package provider

import "context"

type TranscribeRequest struct {
	AudioPath       string
	Format          string
	SampleRateHz    int
	Channels        int
	Language        string
	MaxAudioSeconds float64
}

type TranscribeResult struct {
	Text              string
	Confidence        float64
	IsFinal           bool
	ProviderLatencyMS int64
	AudioDurationMS   int64
}

type SpeakRequest struct {
	Text         string
	Model        string
	Voice        string
	Instructions string
	Format       string
	SampleRateHz int
}

type SpeakResult struct {
	AudioPath         string
	Format            string
	SampleRateHz      int
	DurationMS        int64
	ProviderLatencyMS int64
}

type Provider interface {
	Health(ctx context.Context) error
	Transcribe(ctx context.Context, request TranscribeRequest) (TranscribeResult, error)
	Speak(ctx context.Context, request SpeakRequest) (SpeakResult, error)
}
```

Create `workers/voice/go/internal/provider/mock.go`:

```go
package provider

import (
	"context"
	"os"
	"path/filepath"
)

type MockProvider struct{}

func (MockProvider) Health(ctx context.Context) error {
	return ctx.Err()
}

func (MockProvider) Transcribe(ctx context.Context, request TranscribeRequest) (TranscribeResult, error) {
	if err := ctx.Err(); err != nil {
		return TranscribeResult{}, err
	}
	text := os.Getenv("YOYOPOD_MOCK_TRANSCRIPT")
	if text == "" {
		text = "play music"
	}
	return TranscribeResult{
		Text:              text,
		Confidence:        1.0,
		IsFinal:           true,
		ProviderLatencyMS: 1,
		AudioDurationMS:   0,
	}, nil
}

func (MockProvider) Speak(ctx context.Context, request SpeakRequest) (SpeakResult, error) {
	if err := ctx.Err(); err != nil {
		return SpeakResult{}, err
	}
	path := filepath.Join(os.TempDir(), "yoyopod-mock-tts.wav")
	if err := os.WriteFile(path, []byte("RIFF\x00\x00\x00\x00WAVE"), 0o600); err != nil {
		return SpeakResult{}, err
	}
	return SpeakResult{
		AudioPath:         path,
		Format:            "wav",
		SampleRateHz:      request.SampleRateHz,
		DurationMS:        1,
		ProviderLatencyMS: 1,
	}, nil
}
```

- [ ] **Step 4: Add worker command loop**

Create `workers/voice/go/internal/worker/worker.go` with:

```go
package worker

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"os"
	"sync"
	"time"

	"github.com/moustafattia/yoyopod-core/workers/voice/go/internal/protocol"
	"github.com/moustafattia/yoyopod-core/workers/voice/go/internal/provider"
)

type Worker struct {
	provider provider.Provider
	in       io.Reader
	out      io.Writer
	err      io.Writer
	mu       sync.Mutex
	active   map[string]context.CancelFunc
}

func New(p provider.Provider, in io.Reader, out io.Writer, err io.Writer) *Worker {
	return &Worker{
		provider: p,
		in:       in,
		out:      out,
		err:      err,
		active:   map[string]context.CancelFunc{},
	}
}

func (w *Worker) Run(ctx context.Context) error {
	w.emit("event", "voice.ready", nil, map[string]interface{}{"provider": "mock"})
	scanner := bufio.NewScanner(w.in)
	for scanner.Scan() {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
		envelope, err := protocol.Decode(scanner.Bytes())
		if err != nil {
			fmt.Fprintf(w.err, "protocol error: %v\n", err)
			continue
		}
		w.handle(ctx, envelope)
	}
	return scanner.Err()
}

func (w *Worker) handle(parent context.Context, envelope protocol.Envelope) {
	switch envelope.Type {
	case "voice.health":
		w.handleHealth(parent, envelope)
	case "voice.transcribe":
		w.handleTranscribe(parent, envelope)
	case "voice.speak":
		w.handleSpeak(parent, envelope)
	case "voice.cancel":
		w.handleCancel(envelope)
	case "voice.shutdown":
		w.handleCancelAll()
	default:
		w.emit("error", "voice.error", envelope.RequestID, map[string]interface{}{
			"code":      "unknown_command",
			"message":   "unsupported command: " + envelope.Type,
			"retryable": false,
		})
	}
}

func (w *Worker) handleHealth(parent context.Context, envelope protocol.Envelope) {
	ctx, cancel := w.contextFor(parent, envelope)
	defer cancel()
	if err := w.provider.Health(ctx); err != nil {
		w.emitProviderError(envelope.RequestID, err)
		return
	}
	w.emit("result", "voice.ready", envelope.RequestID, map[string]interface{}{"ok": true})
}

func (w *Worker) handleTranscribe(parent context.Context, envelope protocol.Envelope) {
	if envelope.RequestID == nil {
		w.emitProviderError(nil, fmt.Errorf("voice.transcribe missing request_id"))
		return
	}
	ctx, cancel := w.contextFor(parent, envelope)
	if !w.registerActive(*envelope.RequestID, cancel) {
		cancel()
		w.emit("error", "voice.error", envelope.RequestID, map[string]interface{}{
			"code":      "busy",
			"message":   "voice worker already has an active request",
			"retryable": true,
		})
		return
	}
	go func() {
		defer w.clearActive(*envelope.RequestID)
		defer cancel()
		result, err := w.provider.Transcribe(ctx, provider.TranscribeRequest{
			AudioPath:       stringField(envelope.Payload, "audio_path"),
			Format:          stringField(envelope.Payload, "format"),
			SampleRateHz:    intField(envelope.Payload, "sample_rate_hz"),
			Channels:        intField(envelope.Payload, "channels"),
			Language:        stringField(envelope.Payload, "language"),
			MaxAudioSeconds: floatField(envelope.Payload, "max_audio_seconds"),
		})
		if err != nil {
			w.emitProviderError(envelope.RequestID, err)
			return
		}
		w.emit("result", "voice.transcribe.result", envelope.RequestID, map[string]interface{}{
			"text":                result.Text,
			"confidence":          result.Confidence,
			"is_final":            result.IsFinal,
			"provider_latency_ms": result.ProviderLatencyMS,
			"audio_duration_ms":   result.AudioDurationMS,
		})
	}()
}

func (w *Worker) handleSpeak(parent context.Context, envelope protocol.Envelope) {
	if envelope.RequestID == nil {
		w.emitProviderError(nil, fmt.Errorf("voice.speak missing request_id"))
		return
	}
	ctx, cancel := w.contextFor(parent, envelope)
	if !w.registerActive(*envelope.RequestID, cancel) {
		cancel()
		w.emit("error", "voice.error", envelope.RequestID, map[string]interface{}{
			"code":      "busy",
			"message":   "voice worker already has an active request",
			"retryable": true,
		})
		return
	}
	go func() {
		defer w.clearActive(*envelope.RequestID)
		defer cancel()
		result, err := w.provider.Speak(ctx, provider.SpeakRequest{
			Text:         stringField(envelope.Payload, "text"),
			Model:        stringField(envelope.Payload, "model"),
			Voice:        stringField(envelope.Payload, "voice"),
			Instructions: stringField(envelope.Payload, "instructions"),
			Format:       stringField(envelope.Payload, "format"),
			SampleRateHz: intField(envelope.Payload, "sample_rate_hz"),
		})
		if err != nil {
			w.emitProviderError(envelope.RequestID, err)
			return
		}
		w.emit("result", "voice.speak.result", envelope.RequestID, map[string]interface{}{
			"audio_path":          result.AudioPath,
			"format":              result.Format,
			"sample_rate_hz":      result.SampleRateHz,
			"duration_ms":         result.DurationMS,
			"provider_latency_ms": result.ProviderLatencyMS,
		})
	}()
}

func (w *Worker) handleCancel(envelope protocol.Envelope) {
	requestID := stringField(envelope.Payload, "request_id")
	w.mu.Lock()
	cancel := w.active[requestID]
	w.mu.Unlock()
	if cancel != nil {
		cancel()
	}
	w.emit("result", "voice.cancelled", &requestID, map[string]interface{}{"cancelled": true})
}

func (w *Worker) handleCancelAll() {
	w.mu.Lock()
	defer w.mu.Unlock()
	for requestID, cancel := range w.active {
		cancel()
		delete(w.active, requestID)
	}
}

func (w *Worker) registerActive(requestID string, cancel context.CancelFunc) bool {
	w.mu.Lock()
	defer w.mu.Unlock()
	if len(w.active) > 0 {
		return false
	}
	w.active[requestID] = cancel
	return true
}

func (w *Worker) clearActive(requestID string) {
	w.mu.Lock()
	defer w.mu.Unlock()
	delete(w.active, requestID)
}

func (w *Worker) contextFor(parent context.Context, envelope protocol.Envelope) (context.Context, context.CancelFunc) {
	timeout := time.Duration(envelope.DeadlineMS) * time.Millisecond
	if timeout <= 0 {
		timeout = 12 * time.Second
	}
	return context.WithTimeout(parent, timeout)
}

func (w *Worker) emitProviderError(requestID *string, err error) {
	code := "provider_error"
	if err == context.DeadlineExceeded {
		code = "deadline_exceeded"
	}
	if err == context.Canceled {
		code = "cancelled"
	}
	w.emit("error", "voice.error", requestID, map[string]interface{}{
		"code":      code,
		"message":   err.Error(),
		"retryable": code != "cancelled",
	})
}

func (w *Worker) emit(kind string, typ string, requestID *string, payload map[string]interface{}) {
	line, err := protocol.Encode(protocol.Envelope{
		SchemaVersion: protocol.SchemaVersion,
		Kind:          kind,
		Type:          typ,
		RequestID:     requestID,
		TimestampMS:   time.Now().UnixMilli(),
		DeadlineMS:    0,
		Payload:       payload,
	})
	if err != nil {
		fmt.Fprintf(w.err, "encode error: %v\n", err)
		return
	}
	fmt.Fprintln(w.out, string(line))
}

func stringField(payload map[string]interface{}, key string) string {
	value, _ := payload[key].(string)
	return value
}

func intField(payload map[string]interface{}, key string) int {
	switch value := payload[key].(type) {
	case float64:
		return int(value)
	case int:
		return value
	default:
		return 0
	}
}

func floatField(payload map[string]interface{}, key string) float64 {
	value, _ := payload[key].(float64)
	return value
}

func RunDefault() error {
	return New(provider.MockProvider{}, os.Stdin, os.Stdout, os.Stderr).Run(context.Background())
}
```

- [ ] **Step 5: Add entrypoint**

Create `workers/voice/go/cmd/yoyopod-voice-worker/main.go`:

```go
package main

import (
	"log"

	"github.com/moustafattia/yoyopod-core/workers/voice/go/internal/worker"
)

func main() {
	if err := worker.RunDefault(); err != nil {
		log.Fatal(err)
	}
}
```

- [ ] **Step 6: Add Go worker tests**

Create `workers/voice/go/internal/worker/worker_test.go`:

```go
package worker

import (
	"bytes"
	"context"
	"strings"
	"testing"

	"github.com/moustafattia/yoyopod-core/workers/voice/go/internal/protocol"
	"github.com/moustafattia/yoyopod-core/workers/voice/go/internal/provider"
)

func TestWorkerTranscribeWithMockProvider(t *testing.T) {
	requestID := "req-1"
	input := protocol.Envelope{
		SchemaVersion: protocol.SchemaVersion,
		Kind:          "command",
		Type:          "voice.transcribe",
		RequestID:     &requestID,
		DeadlineMS:    1000,
		Payload: map[string]interface{}{
			"audio_path":         "/tmp/input.wav",
			"format":             "wav",
			"sample_rate_hz":     16000,
			"channels":           1,
			"language":           "en",
			"max_audio_seconds":  30.0,
		},
	}
	line, err := protocol.Encode(input)
	if err != nil {
		t.Fatal(err)
	}
	stdin := bytes.NewBuffer(append(line, '\n'))
	var stdout bytes.Buffer
	var stderr bytes.Buffer

	err = New(provider.MockProvider{}, stdin, &stdout, &stderr).Run(context.Background())
	if err != nil {
		t.Fatal(err)
	}

	output := stdout.String()
	if !strings.Contains(output, "voice.ready") {
		t.Fatalf("missing ready event: %s", output)
	}
	if !strings.Contains(output, "voice.transcribe.result") {
		t.Fatalf("missing transcribe result: %s", output)
	}
	if !strings.Contains(output, "play music") {
		t.Fatalf("missing transcript: %s", output)
	}
}
```

- [ ] **Step 7: Run Go tests**

Run:

```bash
cd workers/voice/go
go test ./...
```

Expected: pass.

- [ ] **Step 8: Commit**

Run:

```bash
git add workers/voice/go
git commit -m "feat: add go voice worker fake provider"
```

---

## Task 7: Add OpenAI Provider to Go Worker

**Files:**

- Modify: `workers/voice/go/internal/provider/openai.go`
- Modify: `workers/voice/go/internal/worker/worker.go`
- Modify: `workers/voice/go/cmd/yoyopod-voice-worker/main.go`
- Test: `workers/voice/go/internal/provider/openai_test.go`

- [ ] **Step 1: Add OpenAI provider tests**

Create `workers/voice/go/internal/provider/openai_test.go`:

```go
package provider

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestOpenAITranscribeSendsMultipartRequest(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/audio/transcriptions" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		if got := r.Header.Get("Authorization"); got != "Bearer test-key" {
			t.Fatalf("unexpected auth header: %s", got)
		}
		if err := r.ParseMultipartForm(10 << 20); err != nil {
			t.Fatal(err)
		}
		if got := r.FormValue("model"); got != "gpt-4o-mini-transcribe" {
			t.Fatalf("unexpected model: %s", got)
		}
		_ = json.NewEncoder(w).Encode(map[string]interface{}{
			"text": "play music",
		})
	}))
	defer server.Close()

	provider := OpenAIProvider{
		BaseURL: server.URL,
		APIKey:  "test-key",
		STTModel: "gpt-4o-mini-transcribe",
		TTSModel: "gpt-4o-mini-tts",
		TTSVoice: "alloy",
		Client: server.Client(),
	}

	result, err := provider.Transcribe(context.Background(), TranscribeRequest{
		AudioPath: "../../testdata/input.wav",
		Format: "wav",
		SampleRateHz: 16000,
		Channels: 1,
		Language: "en",
	})
	if err != nil {
		t.Fatal(err)
	}
	if result.Text != "play music" {
		t.Fatalf("unexpected text: %s", result.Text)
	}
}

func TestOpenAISpeakWritesWavFile(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/audio/speech" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		var payload map[string]interface{}
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Fatal(err)
		}
		if payload["model"] != "gpt-4o-mini-tts" {
			t.Fatalf("unexpected model: %v", payload["model"])
		}
		w.Header().Set("Content-Type", "audio/wav")
		_, _ = w.Write([]byte("RIFF\x00\x00\x00\x00WAVE"))
	}))
	defer server.Close()

	provider := OpenAIProvider{
		BaseURL: server.URL,
		APIKey:  "test-key",
		STTModel: "gpt-4o-mini-transcribe",
		TTSModel: "gpt-4o-mini-tts",
		TTSVoice: "alloy",
		Client: server.Client(),
	}

	result, err := provider.Speak(context.Background(), SpeakRequest{
		Text: "Playing music",
		Model: "gpt-4o-mini-tts",
		Voice: "alloy",
		Instructions: "Speak clearly.",
		Format: "wav",
		SampleRateHz: 16000,
	})
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasSuffix(result.AudioPath, ".wav") {
		t.Fatalf("expected wav output path, got %s", result.AudioPath)
	}
}
```

Add a tiny fixture file:

```bash
mkdir -p workers/voice/go/internal/testdata
printf 'RIFF\0\0\0\0WAVE' > workers/voice/go/internal/testdata/input.wav
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
cd workers/voice/go
go test ./...
```

Expected: fails because `OpenAIProvider` does not exist.

- [ ] **Step 3: Implement OpenAI provider**

Create `workers/voice/go/internal/provider/openai.go`:

```go
package provider

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"time"
)

type OpenAIProvider struct {
	BaseURL  string
	APIKey   string
	STTModel string
	TTSModel string
	TTSVoice string
	Client   *http.Client
}

func NewOpenAIProviderFromEnv() OpenAIProvider {
	baseURL := os.Getenv("OPENAI_BASE_URL")
	if baseURL == "" {
		baseURL = "https://api.openai.com"
	}
	sttModel := os.Getenv("YOYOPOD_CLOUD_STT_MODEL")
	if sttModel == "" {
		sttModel = "gpt-4o-mini-transcribe"
	}
	ttsModel := os.Getenv("YOYOPOD_CLOUD_TTS_MODEL")
	if ttsModel == "" {
		ttsModel = "gpt-4o-mini-tts"
	}
	ttsVoice := os.Getenv("YOYOPOD_CLOUD_TTS_VOICE")
	if ttsVoice == "" {
		ttsVoice = "alloy"
	}
	return OpenAIProvider{
		BaseURL:  baseURL,
		APIKey:   os.Getenv("OPENAI_API_KEY"),
		STTModel: sttModel,
		TTSModel: ttsModel,
		TTSVoice: ttsVoice,
		Client:   &http.Client{Timeout: 30 * time.Second},
	}
}

func (p OpenAIProvider) Health(ctx context.Context) error {
	if p.APIKey == "" {
		return fmt.Errorf("OPENAI_API_KEY is not set")
	}
	return ctx.Err()
}

func (p OpenAIProvider) Transcribe(ctx context.Context, request TranscribeRequest) (TranscribeResult, error) {
	startedAt := time.Now()
	if p.APIKey == "" {
		return TranscribeResult{}, fmt.Errorf("OPENAI_API_KEY is not set")
	}
	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	_ = writer.WriteField("model", p.STTModel)
	if request.Language != "" {
		_ = writer.WriteField("language", request.Language)
	}
	_ = writer.WriteField("response_format", "json")
	fileWriter, err := writer.CreateFormFile("file", filepath.Base(request.AudioPath))
	if err != nil {
		return TranscribeResult{}, err
	}
	file, err := os.Open(request.AudioPath)
	if err != nil {
		return TranscribeResult{}, err
	}
	if _, err := io.Copy(fileWriter, file); err != nil {
		_ = file.Close()
		return TranscribeResult{}, err
	}
	_ = file.Close()
	if err := writer.Close(); err != nil {
		return TranscribeResult{}, err
	}
	httpRequest, err := http.NewRequestWithContext(ctx, http.MethodPost, p.BaseURL+"/v1/audio/transcriptions", &body)
	if err != nil {
		return TranscribeResult{}, err
	}
	httpRequest.Header.Set("Authorization", "Bearer "+p.APIKey)
	httpRequest.Header.Set("Content-Type", writer.FormDataContentType())
	response, err := p.client().Do(httpRequest)
	if err != nil {
		return TranscribeResult{}, err
	}
	defer response.Body.Close()
	if response.StatusCode >= 400 {
		payload, _ := io.ReadAll(io.LimitReader(response.Body, 4096))
		return TranscribeResult{}, fmt.Errorf("openai transcription failed: status=%d body=%s", response.StatusCode, string(payload))
	}
	var decoded struct {
		Text string `json:"text"`
	}
	if err := json.NewDecoder(response.Body).Decode(&decoded); err != nil {
		return TranscribeResult{}, err
	}
	return TranscribeResult{
		Text:              decoded.Text,
		Confidence:        1.0,
		IsFinal:           true,
		ProviderLatencyMS: time.Since(startedAt).Milliseconds(),
	}, nil
}

func (p OpenAIProvider) Speak(ctx context.Context, request SpeakRequest) (SpeakResult, error) {
	startedAt := time.Now()
	if p.APIKey == "" {
		return SpeakResult{}, fmt.Errorf("OPENAI_API_KEY is not set")
	}
	model := request.Model
	if model == "" {
		model = p.TTSModel
	}
	voice := request.Voice
	if voice == "" {
		voice = p.TTSVoice
	}
	payload := map[string]interface{}{
		"model":           model,
		"voice":           voice,
		"input":           request.Text,
		"instructions":    request.Instructions,
		"response_format": "wav",
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return SpeakResult{}, err
	}
	httpRequest, err := http.NewRequestWithContext(ctx, http.MethodPost, p.BaseURL+"/v1/audio/speech", bytes.NewReader(body))
	if err != nil {
		return SpeakResult{}, err
	}
	httpRequest.Header.Set("Authorization", "Bearer "+p.APIKey)
	httpRequest.Header.Set("Content-Type", "application/json")
	response, err := p.client().Do(httpRequest)
	if err != nil {
		return SpeakResult{}, err
	}
	defer response.Body.Close()
	if response.StatusCode >= 400 {
		payload, _ := io.ReadAll(io.LimitReader(response.Body, 4096))
		return SpeakResult{}, fmt.Errorf("openai speech failed: status=%d body=%s", response.StatusCode, string(payload))
	}
	output, err := os.CreateTemp("", "yoyopod-cloud-tts-*.wav")
	if err != nil {
		return SpeakResult{}, err
	}
	defer output.Close()
	if _, err := io.Copy(output, response.Body); err != nil {
		return SpeakResult{}, err
	}
	return SpeakResult{
		AudioPath:         output.Name(),
		Format:            "wav",
		SampleRateHz:      request.SampleRateHz,
		ProviderLatencyMS: time.Since(startedAt).Milliseconds(),
	}, nil
}

func (p OpenAIProvider) client() *http.Client {
	if p.Client != nil {
		return p.Client
	}
	return &http.Client{Timeout: 30 * time.Second}
}
```

- [ ] **Step 4: Select provider from environment**

In `workers/voice/go/cmd/yoyopod-voice-worker/main.go`, replace the entrypoint with:

```go
package main

import (
	"context"
	"log"
	"os"

	"github.com/moustafattia/yoyopod-core/workers/voice/go/internal/provider"
	"github.com/moustafattia/yoyopod-core/workers/voice/go/internal/worker"
)

func main() {
	var selected provider.Provider = provider.MockProvider{}
	if os.Getenv("YOYOPOD_VOICE_WORKER_PROVIDER") == "openai" {
		selected = provider.NewOpenAIProviderFromEnv()
	}
	if err := worker.New(selected, os.Stdin, os.Stdout, os.Stderr).Run(context.Background()); err != nil {
		log.Fatal(err)
	}
}
```

- [ ] **Step 5: Run Go tests**

Run:

```bash
cd workers/voice/go
go test ./...
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add workers/voice/go
git commit -m "feat: add openai voice worker provider"
```

---

## Task 8: Add Go Worker Build and Python Integration Test

**Files:**

- Modify: `yoyopod_cli/build.py`
- Test: `tests/core/test_go_voice_worker_contract.py`

- [ ] **Step 1: Add Python integration test**

Create `tests/core/test_go_voice_worker_contract.py`:

```python
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_go_voice_worker_mock_transcribe_contract(tmp_path: Path) -> None:
    if shutil.which("go") is None:
        pytest.skip("go toolchain not available")
    worker_dir = Path("workers/voice/go")
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
    request_id = "req-contract"
    command = {
        "schema_version": 1,
        "kind": "command",
        "type": "voice.transcribe",
        "request_id": request_id,
        "timestamp_ms": 1,
        "deadline_ms": 1000,
        "payload": {
            "audio_path": str(audio_path),
            "format": "wav",
            "sample_rate_hz": 16000,
            "channels": 1,
            "language": "en",
            "max_audio_seconds": 30.0,
        },
    }
    result = subprocess.run(
        ["go", "run", "./cmd/yoyopod-voice-worker"],
        input=json.dumps(command) + "\n",
        cwd=worker_dir,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0
    envelopes = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert any(envelope["type"] == "voice.ready" for envelope in envelopes)
    transcript = next(
        envelope for envelope in envelopes if envelope["type"] == "voice.transcribe.result"
    )
    assert transcript["request_id"] == request_id
    assert transcript["payload"]["text"] == "play music"
```

- [ ] **Step 2: Run test**

Run:

```bash
uv run pytest -q tests/core/test_go_voice_worker_contract.py
```

Expected: pass when Go is available; skip when Go is not available.

- [ ] **Step 3: Add build helper**

In `yoyopod_cli/build.py`, add these helpers near the other build helper functions:

```python
def _voice_worker_dir() -> Path:
    return _REPO_ROOT / "workers" / "voice" / "go"


def _voice_worker_binary_path() -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return _voice_worker_dir() / "build" / f"yoyopod-voice-worker{suffix}"


def build_voice_worker() -> Path:
    """Build the Go cloud voice worker and return the binary path."""

    worker_dir = _voice_worker_dir()
    output = _voice_worker_binary_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    _run(
        ["go", "build", "-o", str(output), "./cmd/yoyopod-voice-worker"],
        cwd=worker_dir,
    )
    return output
```

Add this Typer command near the other `@app.command(...)` build commands:

```python
@app.command("voice-worker")
def build_voice_worker_command() -> None:
    """Build the Go cloud voice worker for the current platform."""

    output = build_voice_worker()
    typer.echo(f"Built Go voice worker: {output}")
```

The command should be:

```bash
uv run yoyopod build voice-worker
```

Expected behavior:

- builds `workers/voice/go/build/yoyopod-voice-worker` on Linux
- builds `workers/voice/go/build/yoyopod-voice-worker.exe` on Windows
- exits non-zero if `go` is missing

- [ ] **Step 4: Add CLI build test**

Add this to `tests/cli/test_yoyopod_cli_build.py`:

```python
def test_build_voice_worker_invokes_go_build(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(
        build_cli,
        "_run",
        lambda command, cwd=None: calls.append((command, cwd)),
    )

    output = build_cli.build_voice_worker()

    assert output.name.startswith("yoyopod-voice-worker")
    assert calls == [
        (
            [
                "go",
                "build",
                "-o",
                str(output),
                "./cmd/yoyopod-voice-worker",
            ],
            build_cli._REPO_ROOT / "workers" / "voice" / "go",
        )
    ]


def test_voice_worker_build_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["voice-worker", "--help"])

    assert result.exit_code == 0
    assert "go cloud voice worker" in result.output.lower()
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest -q tests/core/test_go_voice_worker_contract.py tests/cli/test_yoyopod_cli_build.py
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add yoyopod_cli/build.py tests/core/test_go_voice_worker_contract.py tests/yoyopod_cli workers/voice/go
git commit -m "feat: build go voice worker"
```

---

## Task 9: Enable Cloud STT Path

**Files:**

- Modify: `yoyopod/core/bootstrap/screens_boot.py`
- Modify: `yoyopod/integrations/voice/runtime.py`
- Test: `tests/integrations/voice/test_runtime.py`
- Test: `tests/e2e/test_app_orchestration.py`

- [ ] **Step 1: Add runtime STT test using fake worker backend**

Add to `tests/integrations/voice/test_runtime.py`:

```python
def test_listening_cycle_uses_cloud_worker_transcript(tmp_path: Path) -> None:
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"RIFF")
    outcomes: list[VoiceCommandOutcome] = []

    class _VoiceService:
        def capture_available(self) -> bool:
            return True

        def stt_available(self) -> bool:
            return True

        def tts_available(self) -> bool:
            return False

        def capture_audio(self, _request):
            return VoiceCaptureResult(audio_path=audio_path, recorded=True)

        def transcribe(self, path):
            assert path == audio_path
            return VoiceTranscript(text="play music", confidence=1.0, is_final=True)

        def speak(self, _text: str) -> bool:
            return False

    runtime = VoiceRuntimeCoordinator(
        context=None,
        settings_resolver=_SettingsResolver(),
        command_executor=_CommandExecutor(),
        voice_service_factory=lambda _settings: _VoiceService(),
    )
    runtime.bind(
        state_listener=None,
        outcome_listener=outcomes.append,
        dispatcher=lambda callback: callback(),
    )

    runtime.begin_listening(async_capture=False)

    assert outcomes[-1].headline == "Done"
    assert not audio_path.exists()
```

- [ ] **Step 2: Run focused test**

Run:

```bash
uv run pytest -q tests/integrations/voice/test_runtime.py::test_listening_cycle_uses_cloud_worker_transcript
```

Expected: pass if Task 5 wiring preserved the existing `VoiceManager` interface.

- [ ] **Step 3: Add degraded Ask outcome for cloud worker unavailable**

In `VoiceRuntimeCoordinator._prepare_capture()`, keep the current capture and STT checks, but change the no-STT message to depend on `settings.mode`:

```python
settings = self.settings()
if not voice_service.stt_available():
    if settings.mode == "cloud":
        return VoiceCommandOutcome(
            "Speech Offline",
            "Cloud speech is unavailable. Local controls still work.",
            should_speak=False,
        )
    return VoiceCommandOutcome(
        "Speech Offline",
        "The offline speech model is not installed yet.",
        should_speak=False,
    )
```

- [ ] **Step 4: Add degraded test**

Add:

```python
def test_cloud_voice_unavailable_keeps_local_feedback_message() -> None:
    class _VoiceService:
        def capture_available(self) -> bool:
            return True

        def stt_available(self) -> bool:
            return False

        def tts_available(self) -> bool:
            return False

    runtime = VoiceRuntimeCoordinator(
        context=None,
        settings_resolver=_SettingsResolver(settings=VoiceSettings(mode="cloud")),
        command_executor=_CommandExecutor(),
        voice_service_factory=lambda _settings: _VoiceService(),
    )
    outcomes: list[VoiceCommandOutcome] = []
    runtime.bind(
        state_listener=None,
        outcome_listener=outcomes.append,
        dispatcher=lambda callback: callback(),
    )

    runtime.begin_listening(async_capture=False)

    assert runtime.state.headline == "Speech Offline"
    assert "Local controls still work" in runtime.state.body
```

- [ ] **Step 5: Run runtime tests**

Run:

```bash
uv run pytest -q tests/integrations/voice/test_runtime.py tests/e2e/test_app_orchestration.py
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add yoyopod/core/bootstrap/screens_boot.py yoyopod/integrations/voice/runtime.py tests/integrations/voice/test_runtime.py tests/e2e/test_app_orchestration.py
git commit -m "feat: route cloud voice stt through worker"
```

---

## Task 10: Enable Cloud TTS Path

**Files:**

- Modify: `yoyopod/integrations/voice/runtime.py`
- Modify: `tests/integrations/voice/test_runtime.py`

- [ ] **Step 1: Add TTS does not block action handling test**

Add:

```python
def test_spoken_outcome_does_not_block_main_thread() -> None:
    started = threading.Event()
    release = threading.Event()

    class _VoiceService:
        def speak(self, _text: str) -> bool:
            started.set()
            release.wait(timeout=2.0)
            return True

    runtime = VoiceRuntimeCoordinator(
        context=None,
        settings_resolver=_SettingsResolver(),
        command_executor=_CommandExecutor(),
        voice_service_factory=lambda _settings: _VoiceService(),
    )

    started_at = time.monotonic()
    runtime._apply_outcome(VoiceCommandOutcome("Done", "Playing music", should_speak=True))
    elapsed = time.monotonic() - started_at

    assert elapsed < 0.2
    assert started.wait(timeout=1.0)
    release.set()
```

- [ ] **Step 2: Run test**

Run:

```bash
uv run pytest -q tests/integrations/voice/test_runtime.py::test_spoken_outcome_does_not_block_main_thread
```

Expected: pass after Task 5.

- [ ] **Step 3: Add cloud TTS failure logging test**

Add:

```python
def test_spoken_outcome_failure_does_not_change_successful_command_outcome(caplog) -> None:
    class _VoiceService:
        def speak(self, _text: str) -> bool:
            return False

    runtime = VoiceRuntimeCoordinator(
        context=None,
        settings_resolver=_SettingsResolver(),
        command_executor=_CommandExecutor(),
        voice_service_factory=lambda _settings: _VoiceService(),
    )

    runtime._apply_outcome(VoiceCommandOutcome("Done", "Playing music", should_speak=True))

    assert runtime.state.headline == "Done"
    assert runtime.state.body == "Playing music"
```

- [ ] **Step 4: Run voice runtime tests**

Run:

```bash
uv run pytest -q tests/integrations/voice/test_runtime.py
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add yoyopod/integrations/voice/runtime.py tests/integrations/voice/test_runtime.py
git commit -m "feat: keep cloud voice tts off ui path"
```

---

## Task 11: Add Pi Measurement Workflow

**Files:**

- Modify: `docs/PI_PROFILING_WORKFLOW.md`
- Test: docs grep command

- [ ] **Step 1: Add Phase 2 profiling section**

Append this section to `docs/PI_PROFILING_WORKFLOW.md`:

```markdown
## Runtime Hybrid Phase 2 Cloud Voice Measurement

Use this after the Go cloud voice worker is wired behind the feature flag.

### Build and deploy

```bash
uv run yoyopod build voice-worker
yoyopod remote mode activate dev
yoyopod remote sync --branch <branch>
```

### Required scenarios

Capture status and process memory for each scenario:

- voice disabled
- local Vosk configured and one transcription attempted
- Go voice worker idle with mock provider
- Go voice worker cloud STT request
- Go voice worker cloud TTS request
- provider unavailable or missing credentials
- worker crash and supervisor restart

### Fields to record

- supervisor PSS/RSS
- voice worker PSS/RSS
- total process tree PSS/RSS
- `responsiveness_input_to_action_p95_ms`
- `responsiveness_action_to_visible_p95_ms`
- `runtime_main_thread_drain_seconds`
- voice worker pending requests
- voice worker restart count
- protocol errors and dropped messages

### Acceptance target

Cloud voice mode is acceptable only if STT/TTS requests avoid UI-loop stalls and total PSS is lower than the current local Vosk command path when Vosk is resident.
```

- [ ] **Step 2: Verify heading appears once**

Run:

```powershell
Select-String -Path docs/PI_PROFILING_WORKFLOW.md -Pattern "Runtime Hybrid Phase 2 Cloud Voice Measurement"
```

Expected: exactly one matching heading.

- [ ] **Step 3: Commit**

Run:

```bash
git add docs/PI_PROFILING_WORKFLOW.md
git commit -m "docs: add cloud voice worker profiling workflow"
```

---

## Task 12: Final Verification and Hardware Dev Lane

**Files:**

- Verify all changed files from Tasks 1-11.

- [ ] **Step 1: Run focused Python tests**

Run:

```bash
uv run pytest -q tests/config/test_config_models.py tests/integrations/voice/test_worker_contract.py tests/integrations/voice/test_worker_client.py tests/backends/voice/test_cloud_worker.py tests/integrations/voice/test_runtime.py tests/core/test_bootstrap.py tests/core/test_go_voice_worker_contract.py
```

Expected: pass, with `test_go_voice_worker_contract.py` skipped if Go is unavailable.

- [ ] **Step 2: Run Go tests**

Run:

```bash
cd workers/voice/go
go test ./...
```

Expected: pass when Go is installed. If Go is not installed on the development host, install Go or run this step on the Pi/dev host before opening the PR.

- [ ] **Step 3: Run required quality gate**

Run:

```bash
uv run python scripts/quality.py gate
```

Expected: pass.

- [ ] **Step 4: Run full Python suite**

Run:

```bash
uv run pytest -q
```

Expected: pass. On Windows, compare any platform-specific failure against the latest green Linux CI run before changing unrelated code.

- [ ] **Step 5: Build worker**

Run:

```bash
uv run yoyopod build voice-worker
```

Expected: creates `workers/voice/go/build/yoyopod-voice-worker` on Linux or `workers/voice/go/build/yoyopod-voice-worker.exe` on Windows.

- [ ] **Step 6: Hardware validate mock provider mode**

Run:

```bash
uv run yoyopod remote --host rpi-zero --branch <branch> validate --sha <sha>
uv run yoyopod remote --host rpi-zero --branch <branch> restart
ssh rpi-zero "cd /opt/yoyopod-dev/checkout && git rev-parse HEAD && systemctl is-active yoyopod-dev.service"
```

Expected:

- deploy validation passes
- smoke validation passes
- stability validation passes
- service is active on the expected SHA

- [ ] **Step 7: Hardware measure cloud provider mode**

For the dev lane, put the provider secret and voice flags in `/etc/default/yoyopod-dev` on the Pi. Keep the API key out of tracked YAML and PR text:

```bash
sudo install -m 0600 -o root -g root /dev/null /etc/default/yoyopod-dev
sudo tee /etc/default/yoyopod-dev >/dev/null <<'EOF'
OPENAI_API_KEY=<redacted>
YOYOPOD_VOICE_MODE=cloud
YOYOPOD_VOICE_WORKER_ENABLED=true
YOYOPOD_VOICE_WORKER_PROVIDER=openai
YOYOPOD_STT_BACKEND=cloud-worker
YOYOPOD_TTS_BACKEND=cloud-worker
EOF
sudo systemctl restart yoyopod-dev.service
```

Run the scenarios in `docs/PI_PROFILING_WORKFLOW.md` and record the before/after PSS/RSS values in the PR body.

- [ ] **Step 8: Inspect final status**

Run:

```bash
git status --short
```

Expected: clean working tree after all task commits.

---

## Self-Review

**Spec coverage:** This plan covers the Go worker, provider-neutral supervisor contract, OpenAI as the first concrete provider, fake-provider testing, STT/TTS boundaries, cancellation/deadlines, degraded behavior, local non-speech feedback preservation, and Pi RAM comparison.

**Scope control:** Capture and playback stay in Python. The worker owns cloud provider calls only. Network workerization is not included.

**Type consistency:** Python types flow from `VoiceWorkerClient` to `CloudWorkerSpeechToTextBackend` and `CloudWorkerTextToSpeechBackend`, then through existing `VoiceManager` and `VoiceRuntimeCoordinator`. Go command/result names match the Phase 2 design spec.

**Known execution order:** Do not skip the fake-provider tasks. They make the worker contract testable before cloud credentials, hardware, or provider availability enter the loop.
