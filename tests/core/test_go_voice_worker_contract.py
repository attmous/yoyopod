from __future__ import annotations

import json
import os
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
    env = os.environ.copy()
    env["YOYOPOD_VOICE_WORKER_PROVIDER"] = "mock"
    env["YOYOPOD_MOCK_TRANSCRIPT"] = "play music"
    env.setdefault("GOMAXPROCS", "1")
    env.setdefault("GOFLAGS", "-p=1")

    result = subprocess.run(
        ["go", "run", "./cmd/yoyopod-voice-worker"],
        input=json.dumps(command) + "\n",
        cwd=worker_dir,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0
    assert "voice.ready" in result.stdout
    assert "voice.transcribe.result" in result.stdout
    envelopes = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert any(envelope["type"] == "voice.ready" for envelope in envelopes)
    transcript = next(
        envelope for envelope in envelopes if envelope["type"] == "voice.transcribe.result"
    )
    assert transcript["request_id"] == request_id
    assert transcript["payload"]["text"] == "play music"
