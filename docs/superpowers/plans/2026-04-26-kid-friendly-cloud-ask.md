# Kid-Friendly Cloud Ask Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a kid-friendly conversational Ask mode backed by the Go cloud voice worker, while keeping quick voice commands deterministic and improving command phrase coverage.

**Architecture:** Python keeps ownership of UI state, local command execution, conversation history, cancellation generation, and spoken playback. The Go voice worker gains a `voice.ask` command that calls OpenAI Responses API and returns one bounded answer. The Ask screen chooses command mode when `_quick_command` is true and conversational mode otherwise.

**Tech Stack:** Python 3.12, pytest, dataclass config models, LVGL screen layer, supervised NDJSON worker envelopes, Go 1.x worker, net/http, OpenAI `/v1/responses` and `/v1/audio/speech`.

---

## File Structure

- Modify `config/voice/assistant.yaml`: cloud Ask defaults and child-friendly TTS defaults.
- Modify `yoyopod/config/models/voice.py`: add worker Ask config fields and update TTS default voice/instructions.
- Modify `yoyopod/integrations/voice/models.py`: add Ask worker fields to `VoiceSettings`.
- Modify `yoyopod/integrations/voice/settings.py`: resolve Ask fields from config.
- Modify `yoyopod/core/bootstrap/components_boot.py`: pass Ask env to the Go worker.
- Modify `yoyopod/core/bootstrap/screens_boot.py`: expose Ask settings in the runtime `VoiceSettings` snapshot and pass the worker client to `VoiceRuntimeCoordinator`.
- Modify `yoyopod/integrations/voice/worker_contract.py`: add Ask payload/result datatypes and parser/build helpers.
- Modify `yoyopod/integrations/voice/worker_client.py`: add blocking `ask()` request helper with cancellation.
- Modify `yoyopod/integrations/voice/__init__.py`: export Ask worker datatypes/helpers.
- Create `yoyopod/integrations/voice/ask_conversation.py`: bounded in-memory Ask history and spoken-exit phrase detection.
- Modify `yoyopod/integrations/voice/runtime.py`: add command-vs-conversation entry paths and Ask turn execution.
- Modify `yoyopod/ui/screens/navigation/ask/__init__.py`: call conversational Ask mode outside quick command mode and update hints.
- Modify `yoyopod/integrations/voice/commands.py`: add deterministic phrase variations for existing commands only.
- Modify `workers/voice/go/internal/provider/provider.go`: add `Ask` request/result API.
- Modify `workers/voice/go/internal/provider/mock.go`: deterministic mock Ask answer.
- Modify `workers/voice/go/internal/provider/openai.go`: OpenAI Responses API request/response handling.
- Modify `workers/voice/go/internal/worker/worker.go`: dispatch `voice.ask`.
- Modify `docs/CLOUD_VOICE_WORKER.md`: document Ask/TTS env setup and validation.

Test files:

- Modify `tests/config/test_config_models.py`
- Modify `tests/core/test_bootstrap.py`
- Modify `tests/integrations/test_voice_runtime.py`
- Modify `tests/integrations/voice/test_worker_contract.py`
- Modify `tests/integrations/voice/test_worker_client.py`
- Modify `tests/integrations/test_voice_service.py`
- Modify `tests/ui/test_screen_routing.py`
- Modify `workers/voice/go/internal/provider/openai_test.go`
- Modify `workers/voice/go/internal/worker/worker_test.go`

---

### Task 1: Config And Stable TTS Defaults

**Files:**
- Modify: `config/voice/assistant.yaml`
- Modify: `yoyopod/config/models/voice.py`
- Modify: `yoyopod/integrations/voice/models.py`
- Modify: `yoyopod/integrations/voice/settings.py`
- Modify: `yoyopod/core/bootstrap/components_boot.py`
- Modify: `yoyopod/core/bootstrap/screens_boot.py`
- Test: `tests/config/test_config_models.py`
- Test: `tests/core/test_bootstrap.py`
- Test: `tests/integrations/test_voice_runtime.py`

- [ ] **Step 1: Write config model tests for Ask env fields**

Add assertions to the existing voice worker config test in `tests/config/test_config_models.py` so these env vars are covered:

```python
monkeypatch.setenv("YOYOPOD_CLOUD_ASK_MODEL", "gpt-4.1-mini-test")
monkeypatch.setenv("YOYOPOD_CLOUD_ASK_TIMEOUT_SECONDS", "9.5")
monkeypatch.setenv("YOYOPOD_CLOUD_ASK_MAX_HISTORY_TURNS", "3")
monkeypatch.setenv("YOYOPOD_CLOUD_ASK_MAX_RESPONSE_CHARS", "321")
monkeypatch.setenv("YOYOPOD_CLOUD_ASK_INSTRUCTIONS", "Answer like a calm test helper.")

voice_config = VoiceConfig()

assert voice_config.worker.ask_model == "gpt-4.1-mini-test"
assert voice_config.worker.ask_timeout_seconds == 9.5
assert voice_config.worker.ask_max_history_turns == 3
assert voice_config.worker.ask_max_response_chars == 321
assert voice_config.worker.ask_instructions == "Answer like a calm test helper."
```

- [ ] **Step 2: Run config tests and verify they fail**

Run:

```bash
uv run pytest tests/config/test_config_models.py -q
```

Expected: failure because `VoiceWorkerConfig` has no `ask_*` fields.

- [ ] **Step 3: Add Ask config fields and child-friendly TTS defaults**

In `yoyopod/config/models/voice.py`, extend `VoiceWorkerConfig`:

```python
tts_voice: str = config_value(default="coral", env="YOYOPOD_CLOUD_TTS_VOICE")
tts_instructions: str = config_value(
    default=(
        "Speak warmly and calmly for a child. Use simple words, friendly pacing, "
        "and brief answers. Avoid scary emphasis."
    ),
    env="YOYOPOD_CLOUD_TTS_INSTRUCTIONS",
)
ask_model: str = config_value(default="gpt-4.1-mini", env="YOYOPOD_CLOUD_ASK_MODEL")
ask_timeout_seconds: float = config_value(
    default=12.0,
    env="YOYOPOD_CLOUD_ASK_TIMEOUT_SECONDS",
)
ask_max_history_turns: int = config_value(
    default=4,
    env="YOYOPOD_CLOUD_ASK_MAX_HISTORY_TURNS",
)
ask_max_response_chars: int = config_value(
    default=480,
    env="YOYOPOD_CLOUD_ASK_MAX_RESPONSE_CHARS",
)
ask_instructions: str = config_value(
    default=(
        "You are YoYoPod's friendly Ask helper for a child using a small handheld "
        "audio device. Answer in simple language a child can understand. Keep "
        "answers to 1-3 short sentences unless the child asks for a story. Be "
        "warm, calm, and encouraging. Do not use scary detail. Do not ask for "
        "private information. For medical, legal, safety, emergency, or adult "
        "topics, give a brief safe answer and say to ask a grown-up. If you are "
        "unsure, say so simply. Do not claim to browse the internet or know live facts."
    ),
    env="YOYOPOD_CLOUD_ASK_INSTRUCTIONS",
)
```

In `config/voice/assistant.yaml`, update worker defaults:

```yaml
  tts_voice: "coral"
  tts_instructions: "Speak warmly and calmly for a child. Use simple words, friendly pacing, and brief answers. Avoid scary emphasis."
  ask_model: "gpt-4.1-mini"
  ask_timeout_seconds: 12.0
  ask_max_history_turns: 4
  ask_max_response_chars: 480
  ask_instructions: "You are YoYoPod's friendly Ask helper for a child using a small handheld audio device. Answer in simple language a child can understand. Keep answers to 1-3 short sentences unless the child asks for a story. Be warm, calm, and encouraging. Do not use scary detail. Do not ask for private information. For medical, legal, safety, emergency, or adult topics, give a brief safe answer and say to ask a grown-up. If you are unsure, say so simply. Do not claim to browse the internet or know live facts."
```

- [ ] **Step 4: Add Ask fields to runtime settings**

In `yoyopod/integrations/voice/models.py`, append fields to `VoiceSettings`:

```python
cloud_worker_ask_model: str = "gpt-4.1-mini"
cloud_worker_ask_timeout_seconds: float = 12.0
cloud_worker_ask_max_history_turns: int = 4
cloud_worker_ask_max_response_chars: int = 480
cloud_worker_ask_instructions: str = (
    "You are YoYoPod's friendly Ask helper for a child using a small handheld "
    "audio device. Answer in simple language a child can understand. Keep "
    "answers to 1-3 short sentences unless the child asks for a story. Be "
    "warm, calm, and encouraging. Do not use scary detail. Do not ask for "
    "private information. For medical, legal, safety, emergency, or adult "
    "topics, give a brief safe answer and say to ask a grown-up. If you are "
    "unsure, say so simply. Do not claim to browse the internet or know live facts."
)
```

In `yoyopod/integrations/voice/settings.py`, add these fields in the `VoiceSettings(...)` returned by `defaults()`:

```python
cloud_worker_ask_model=getattr(
    worker_cfg,
    "ask_model",
    defaults.cloud_worker_ask_model,
),
cloud_worker_ask_timeout_seconds=getattr(
    worker_cfg,
    "ask_timeout_seconds",
    defaults.cloud_worker_ask_timeout_seconds,
),
cloud_worker_ask_max_history_turns=getattr(
    worker_cfg,
    "ask_max_history_turns",
    defaults.cloud_worker_ask_max_history_turns,
),
cloud_worker_ask_max_response_chars=getattr(
    worker_cfg,
    "ask_max_response_chars",
    defaults.cloud_worker_ask_max_response_chars,
),
cloud_worker_ask_instructions=getattr(
    worker_cfg,
    "ask_instructions",
    defaults.cloud_worker_ask_instructions,
),
```

- [ ] **Step 5: Pass Ask settings into worker environment and screen runtime snapshot**

In `yoyopod/core/bootstrap/components_boot.py`, add these keys to `_voice_worker_env()`:

```python
"YOYOPOD_CLOUD_ASK_MODEL": getattr(worker_cfg, "ask_model", ""),
"YOYOPOD_CLOUD_ASK_INSTRUCTIONS": getattr(worker_cfg, "ask_instructions", ""),
```

In `yoyopod/core/bootstrap/screens_boot.py`, add these fields to the `VoiceSettings(...)` lambda:

```python
cloud_worker_ask_model=(
    getattr(worker_cfg, "ask_model", "gpt-4.1-mini")
    if worker_cfg is not None
    else "gpt-4.1-mini"
),
cloud_worker_ask_timeout_seconds=(
    getattr(worker_cfg, "ask_timeout_seconds", 12.0)
    if worker_cfg is not None
    else 12.0
),
cloud_worker_ask_max_history_turns=(
    getattr(worker_cfg, "ask_max_history_turns", 4)
    if worker_cfg is not None
    else 4
),
cloud_worker_ask_max_response_chars=(
    getattr(worker_cfg, "ask_max_response_chars", 480)
    if worker_cfg is not None
    else 480
),
cloud_worker_ask_instructions=(
    getattr(worker_cfg, "ask_instructions", VoiceSettings().cloud_worker_ask_instructions)
    if worker_cfg is not None
    else VoiceSettings().cloud_worker_ask_instructions
),
```

When constructing `VoiceRuntimeCoordinator`, pass the cloud worker client:

```python
ask_client=voice_worker_client,
```

- [ ] **Step 6: Update resolver and bootstrap tests**

In `_FakeConfigManager` inside `tests/integrations/test_voice_runtime.py`, add these attributes to `worker`:

```python
ask_model="gpt-4.1-mini",
ask_timeout_seconds=12.0,
ask_max_history_turns=4,
ask_max_response_chars=480,
ask_instructions="Answer like a calm helper.",
```

Extend `test_voice_settings_resolver_includes_cloud_worker_config()`:

```python
voice_cfg.worker.ask_model = "test-ask"
voice_cfg.worker.ask_timeout_seconds = 6.5
voice_cfg.worker.ask_max_history_turns = 2
voice_cfg.worker.ask_max_response_chars = 222
voice_cfg.worker.ask_instructions = "Tiny answers."

assert settings.cloud_worker_ask_model == "test-ask"
assert settings.cloud_worker_ask_timeout_seconds == 6.5
assert settings.cloud_worker_ask_max_history_turns == 2
assert settings.cloud_worker_ask_max_response_chars == 222
assert settings.cloud_worker_ask_instructions == "Tiny answers."
```

In `tests/core/test_bootstrap.py`, extend the voice worker env test:

```python
assert worker_config.env["YOYOPOD_CLOUD_ASK_MODEL"] == "ask-from-yaml"
assert worker_config.env["YOYOPOD_CLOUD_ASK_INSTRUCTIONS"] == "ask instructions from yaml"
```

- [ ] **Step 7: Run focused Python tests**

Run:

```bash
uv run pytest tests/config/test_config_models.py tests/core/test_bootstrap.py tests/integrations/test_voice_runtime.py -q
```

Expected: pass.

- [ ] **Step 8: Commit config foundation**

Run:

```bash
git add config/voice/assistant.yaml yoyopod/config/models/voice.py yoyopod/integrations/voice/models.py yoyopod/integrations/voice/settings.py yoyopod/core/bootstrap/components_boot.py yoyopod/core/bootstrap/screens_boot.py tests/config/test_config_models.py tests/core/test_bootstrap.py tests/integrations/test_voice_runtime.py
git commit --no-verify -m "feat: configure cloud ask settings"
```

---

### Task 2: Python Worker Ask Contract And Client

**Files:**
- Modify: `yoyopod/integrations/voice/worker_contract.py`
- Modify: `yoyopod/integrations/voice/worker_client.py`
- Modify: `yoyopod/integrations/voice/__init__.py`
- Test: `tests/integrations/voice/test_worker_contract.py`
- Test: `tests/integrations/voice/test_worker_client.py`

- [ ] **Step 1: Write worker contract tests**

Add to `tests/integrations/voice/test_worker_contract.py`:

```python
from yoyopod.integrations.voice.worker_contract import (
    VoiceWorkerAskResult,
    VoiceWorkerAskTurn,
    build_ask_payload,
    parse_ask_result,
)


def test_build_ask_payload_includes_bounded_history_and_policy() -> None:
    payload = build_ask_payload(
        question="Why is the sky blue?",
        history=[
            VoiceWorkerAskTurn(role="user", text="What is rain?"),
            VoiceWorkerAskTurn(role="assistant", text="Rain is water from clouds."),
        ],
        model="gpt-4.1-mini",
        instructions="Answer for a child.",
        max_output_chars=480,
    )

    assert payload == {
        "question": "Why is the sky blue?",
        "history": [
            {"role": "user", "text": "What is rain?"},
            {"role": "assistant", "text": "Rain is water from clouds."},
        ],
        "model": "gpt-4.1-mini",
        "instructions": "Answer for a child.",
        "max_output_chars": 480,
    }


def test_parse_ask_result_normalizes_answer() -> None:
    result = parse_ask_result(
        {
            "answer": " The sky scatters blue light. ",
            "model": "gpt-4.1-mini",
            "provider_latency_ms": 612,
        }
    )

    assert result == VoiceWorkerAskResult(
        answer="The sky scatters blue light.",
        model="gpt-4.1-mini",
        provider_latency_ms=612,
    )


def test_parse_ask_result_rejects_empty_answer() -> None:
    with pytest.raises(ValueError, match="answer"):
        parse_ask_result({"answer": "   ", "model": "gpt-4.1-mini"})
```

- [ ] **Step 2: Run contract tests and verify they fail**

Run:

```bash
uv run pytest tests/integrations/voice/test_worker_contract.py -q
```

Expected: import failure for `VoiceWorkerAskResult`, `VoiceWorkerAskTurn`, `build_ask_payload`, and `parse_ask_result`.

- [ ] **Step 3: Implement Ask contract helpers**

In `yoyopod/integrations/voice/worker_contract.py`, add dataclasses:

```python
@dataclass(slots=True, frozen=True)
class VoiceWorkerAskTurn:
    """One bounded conversation turn passed to the voice worker."""

    role: str
    text: str


@dataclass(slots=True, frozen=True)
class VoiceWorkerAskResult:
    """Normalized Ask result returned by a voice worker."""

    answer: str
    model: str
    provider_latency_ms: int | None = None
```

Add helpers:

```python
def build_ask_payload(
    *,
    question: str,
    history: list[VoiceWorkerAskTurn],
    model: str,
    instructions: str,
    max_output_chars: int,
) -> dict[str, Any]:
    """Build a worker payload for one child-friendly Ask turn."""

    return {
        "question": question.strip(),
        "history": [
            {"role": turn.role, "text": turn.text.strip()}
            for turn in history
            if turn.role in {"user", "assistant"} and turn.text.strip()
        ],
        "model": model.strip(),
        "instructions": instructions.strip(),
        "max_output_chars": int(max_output_chars),
    }


def parse_ask_result(payload: Mapping[str, Any]) -> VoiceWorkerAskResult:
    """Parse and normalize an Ask response payload."""

    answer = _required_string(payload, "answer").strip()
    if not answer:
        raise ValueError("answer must be a non-empty string")
    model = str(payload.get("model", "")).strip()
    return VoiceWorkerAskResult(
        answer=answer,
        model=model,
        provider_latency_ms=_optional_int(payload, "provider_latency_ms"),
    )
```

Update `__all__` with the four new names.

- [ ] **Step 4: Write worker client tests**

Add to `tests/integrations/voice/test_worker_client.py`:

```python
from yoyopod.integrations.voice.worker_contract import (
    VoiceWorkerAskResult,
    VoiceWorkerAskTurn,
)


def test_ask_schedules_request_on_main_and_resolves_result() -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.25,
    )
    results: list[VoiceWorkerAskResult] = []

    thread = threading.Thread(
        target=lambda: results.append(
            client.ask(
                question="Why is the sky blue?",
                history=[VoiceWorkerAskTurn(role="user", text="What is rain?")],
                model="gpt-4.1-mini",
                instructions="Answer for a child.",
                max_output_chars=480,
            )
        )
    )
    thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    scheduler.drain()
    request = supervisor.requests[0]

    assert request["domain"] == "voice"
    assert request["type"] == "voice.ask"
    assert request["payload"] == {
        "question": "Why is the sky blue?",
        "history": [{"role": "user", "text": "What is rain?"}],
        "model": "gpt-4.1-mini",
        "instructions": "Answer for a child.",
        "max_output_chars": 480,
    }

    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="result",
            type="voice.ask.result",
            request_id=str(request["request_id"]),
            payload={
                "answer": "Because air scatters blue light.",
                "model": "gpt-4.1-mini",
                "provider_latency_ms": 500,
            },
        )
    )
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert results == [
        VoiceWorkerAskResult(
            answer="Because air scatters blue light.",
            model="gpt-4.1-mini",
            provider_latency_ms=500,
        )
    ]
    assert client.pending_count == 0
```

Add a cancellation test:

```python
def test_ask_cancel_event_sends_worker_cancel_and_unblocks_waiter() -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.25,
    )
    cancel_event = threading.Event()
    errors: list[BaseException] = []

    thread = threading.Thread(
        target=lambda: _capture_error(
            errors,
            lambda: client.ask(
                question="Tell me a story.",
                history=[],
                model="gpt-4.1-mini",
                instructions="Answer for a child.",
                max_output_chars=480,
                cancel_event=cancel_event,
            ),
        )
    )
    thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    scheduler.drain()
    request_id = str(supervisor.requests[0]["request_id"])

    cancel_event.set()
    _wait_until(lambda: len(scheduler.callbacks) == 1)
    scheduler.drain()
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], VoiceWorkerUnavailable)
    assert supervisor.requests[1]["type"] == "voice.cancel"
    assert supervisor.requests[1]["request_id"] == request_id
    assert supervisor.requests[1]["payload"] == {"request_id": request_id}
```

- [ ] **Step 5: Run worker client tests and verify they fail**

Run:

```bash
uv run pytest tests/integrations/voice/test_worker_client.py tests/integrations/voice/test_worker_contract.py -q
```

Expected: failure because `VoiceWorkerClient.ask()` and Ask parser dispatch do not exist.

- [ ] **Step 6: Implement `VoiceWorkerClient.ask()`**

In `yoyopod/integrations/voice/worker_client.py`, import Ask helpers:

```python
VoiceWorkerAskResult,
VoiceWorkerAskTurn,
build_ask_payload,
parse_ask_result,
```

Extend `_PendingRequest.result` union to include `VoiceWorkerAskResult`.

Add method:

```python
def ask(
    self,
    *,
    question: str,
    history: list[VoiceWorkerAskTurn],
    model: str,
    instructions: str,
    max_output_chars: int,
    cancel_event: threading.Event | None = None,
) -> VoiceWorkerAskResult:
    """Send one Ask request and wait for its normalized result."""

    self._raise_if_called_on_main_thread()
    payload = build_ask_payload(
        question=question,
        history=history,
        model=model,
        instructions=instructions,
        max_output_chars=max_output_chars,
    )
    pending = self._send(
        request_type="voice.ask",
        expected_type="voice.ask.result",
        payload=payload,
    )
    result = self._wait_for(pending, cancel_event=cancel_event)
    if isinstance(result, VoiceWorkerAskResult):
        return result
    raise VoiceWorkerUnavailable("voice worker did not return an Ask result")
```

In `_complete_with_result()`, add:

```python
elif event.type == "voice.ask.result":
    result = parse_ask_result(event.payload)
```

Update return union annotations where needed.

- [ ] **Step 7: Export Ask worker symbols**

In `yoyopod/integrations/voice/__init__.py`, add public exports for:

```python
"VoiceWorkerAskResult": ("yoyopod.integrations.voice.worker_contract", "VoiceWorkerAskResult"),
"VoiceWorkerAskTurn": ("yoyopod.integrations.voice.worker_contract", "VoiceWorkerAskTurn"),
"build_ask_payload": ("yoyopod.integrations.voice.worker_contract", "build_ask_payload"),
"parse_ask_result": ("yoyopod.integrations.voice.worker_contract", "parse_ask_result"),
```

Add the same names to `TYPE_CHECKING` imports and `__all__`.

- [ ] **Step 8: Run focused Python worker tests**

Run:

```bash
uv run pytest tests/integrations/voice/test_worker_contract.py tests/integrations/voice/test_worker_client.py -q
```

Expected: pass.

- [ ] **Step 9: Commit Python worker contract**

Run:

```bash
git add yoyopod/integrations/voice/worker_contract.py yoyopod/integrations/voice/worker_client.py yoyopod/integrations/voice/__init__.py tests/integrations/voice/test_worker_contract.py tests/integrations/voice/test_worker_client.py
git commit --no-verify -m "feat: add ask worker client contract"
```

---

### Task 3: Go Worker `voice.ask`

**Files:**
- Modify: `workers/voice/go/internal/provider/provider.go`
- Modify: `workers/voice/go/internal/provider/mock.go`
- Modify: `workers/voice/go/internal/provider/openai.go`
- Modify: `workers/voice/go/internal/worker/worker.go`
- Test: `workers/voice/go/internal/provider/openai_test.go`
- Test: `workers/voice/go/internal/worker/worker_test.go`

- [ ] **Step 1: Write OpenAI provider Ask tests**

Add to `workers/voice/go/internal/provider/openai_test.go`:

```go
func TestOpenAIProviderAskPostsResponsesRequest(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/responses" {
			t.Fatalf("path = %q, want /v1/responses", r.URL.Path)
		}
		if r.Header.Get("Authorization") != "Bearer test-key" {
			t.Fatalf("Authorization = %q, want bearer token", r.Header.Get("Authorization"))
		}
		if r.Header.Get("Content-Type") != "application/json" {
			t.Fatalf("Content-Type = %q, want application/json", r.Header.Get("Content-Type"))
		}
		var payload map[string]any
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Fatalf("Decode returned error: %v", err)
		}
		if payload["model"] != "gpt-4.1-mini" {
			t.Fatalf("model = %v", payload["model"])
		}
		if payload["instructions"] != "Answer for a child." {
			t.Fatalf("instructions = %v", payload["instructions"])
		}
		input, ok := payload["input"].([]any)
		if !ok || len(input) != 3 {
			t.Fatalf("input = %#v, want three messages", payload["input"])
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"output_text":"The sky is blue because air scatters blue light."}`))
	}))
	defer server.Close()

	result, err := OpenAIProvider{
		BaseURL:  server.URL,
		APIKey:   "test-key",
		AskModel: "gpt-4.1-mini",
	}.Ask(context.Background(), AskRequest{
		Question:     "Why is the sky blue?",
		Model:        "gpt-4.1-mini",
		Instructions: "Answer for a child.",
		History: []AskTurn{
			{Role: "user", Text: "What is rain?"},
			{Role: "assistant", Text: "Rain is water from clouds."},
		},
		MaxOutputChars: 480,
	})

	if err != nil {
		t.Fatalf("Ask returned error: %v", err)
	}
	if result.Answer != "The sky is blue because air scatters blue light." {
		t.Fatalf("Answer = %q", result.Answer)
	}
	if result.Model != "gpt-4.1-mini" {
		t.Fatalf("Model = %q", result.Model)
	}
}
```

Add a structured output fallback test:

```go
func TestOpenAIProviderAskParsesStructuredOutputFallback(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"output": [
				{
					"type": "message",
					"content": [
						{"type": "output_text", "text": "A rainbow is sunlight split into colors."}
					]
				}
			]
		}`))
	}))
	defer server.Close()

	result, err := OpenAIProvider{
		BaseURL:  server.URL,
		APIKey:   "test-key",
		AskModel: "gpt-4.1-mini",
	}.Ask(context.Background(), AskRequest{
		Question: "What is a rainbow?",
	})

	if err != nil {
		t.Fatalf("Ask returned error: %v", err)
	}
	if result.Answer != "A rainbow is sunlight split into colors." {
		t.Fatalf("Answer = %q", result.Answer)
	}
}
```

- [ ] **Step 2: Write worker dispatch test**

Add to `workers/voice/go/internal/worker/worker_test.go`:

```go
func TestWorkerHandlesAskCommand(t *testing.T) {
	envelopes, _ := runWorker(
		t,
		provider.MockProvider{},
		protocol.Envelope{
			Kind:      "command",
			Type:      "voice.ask",
			RequestID: "req-ask",
			Payload: map[string]any{
				"question":         "Why is the sky blue?",
				"model":            "gpt-4.1-mini",
				"instructions":     "Answer for a child.",
				"max_output_chars": float64(480),
			},
		},
	)

	result := findEnvelope(t, envelopes, "voice.ask.result")
	if result.RequestID != "req-ask" {
		t.Fatalf("RequestID = %q, want req-ask", result.RequestID)
	}
	if result.Payload["answer"] == "" {
		t.Fatalf("answer is empty in payload %#v", result.Payload)
	}
}
```

Update test fake providers in `worker_test.go` to implement `Ask(ctx, request)`:

```go
func (p *blockingProvider) Ask(ctx context.Context, request provider.AskRequest) (provider.AskResult, error) {
	p.markEntered()
	select {
	case <-ctx.Done():
		return provider.AskResult{}, ctx.Err()
	case <-p.release:
		return provider.AskResult{Answer: "released ask", Model: request.Model}, nil
	}
}
```

For `ignoringCancelProvider`:

```go
func (p *ignoringCancelProvider) Ask(ctx context.Context, request provider.AskRequest) (provider.AskResult, error) {
	close(p.entered)
	<-p.release
	return provider.AskResult{Answer: "late ask", Model: request.Model}, nil
}
```

For `invalidPayloadProvider`:

```go
func (p invalidPayloadProvider) Ask(ctx context.Context, request provider.AskRequest) (provider.AskResult, error) {
	return provider.AskResult{}, provider.InvalidPayload("question is empty")
}
```

- [ ] **Step 3: Run Go tests and verify they fail**

Run:

```bash
Set-Location workers/voice/go
go test ./...
Set-Location ../../..
```

Expected: compile failure because `Provider.Ask`, `AskRequest`, and `OpenAIProvider.Ask` do not exist.

- [ ] **Step 4: Add provider Ask API**

In `workers/voice/go/internal/provider/provider.go`, extend `Provider`:

```go
Ask(context.Context, AskRequest) (AskResult, error)
```

Add structs:

```go
type AskTurn struct {
	Role string `json:"role"`
	Text string `json:"text"`
}

type AskRequest struct {
	Question       string    `json:"question"`
	History        []AskTurn `json:"history"`
	Model          string    `json:"model"`
	Instructions   string    `json:"instructions"`
	MaxOutputChars int       `json:"max_output_chars"`
}

type AskResult struct {
	Answer            string `json:"answer"`
	Model             string `json:"model"`
	ProviderLatencyMS int64  `json:"provider_latency_ms,omitempty"`
}
```

- [ ] **Step 5: Implement mock Ask**

In `workers/voice/go/internal/provider/mock.go`, add:

```go
func (MockProvider) Ask(ctx context.Context, request AskRequest) (AskResult, error) {
	startedAt := time.Now()
	select {
	case <-ctx.Done():
		return AskResult{}, ctx.Err()
	default:
	}

	answer := os.Getenv("YOYOPOD_MOCK_ASK_ANSWER")
	if answer == "" {
		answer = "I can answer that in a small, friendly way."
	}
	model := request.Model
	if model == "" {
		model = "mock"
	}
	return AskResult{
		Answer:            answer,
		Model:             model,
		ProviderLatencyMS: time.Since(startedAt).Milliseconds(),
	}, nil
}
```

- [ ] **Step 6: Implement OpenAI Ask**

In `workers/voice/go/internal/provider/openai.go`, add default and struct field:

```go
defaultOpenAIAskModel = "gpt-4.1-mini"
```

```go
AskModel string
```

In `NewOpenAIProviderFromEnv()`:

```go
AskModel: envOrDefault("YOYOPOD_CLOUD_ASK_MODEL", defaultOpenAIAskModel),
```

Add request/response structs:

```go
type openAIResponsesRequest struct {
	Model        string                `json:"model"`
	Instructions string                `json:"instructions,omitempty"`
	Input        []openAIResponseInput `json:"input"`
}

type openAIResponseInput struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type openAIResponsesResponse struct {
	OutputText string `json:"output_text"`
	Output     []struct {
		Type    string `json:"type"`
		Content []struct {
			Type string `json:"type"`
			Text string `json:"text"`
		} `json:"content"`
	} `json:"output"`
}
```

Add method:

```go
func (p OpenAIProvider) Ask(ctx context.Context, request AskRequest) (AskResult, error) {
	startedAt := time.Now()
	if err := p.requireAPIKey(); err != nil {
		return AskResult{}, err
	}
	question := strings.TrimSpace(request.Question)
	if question == "" {
		return AskResult{}, InvalidPayload("question must be non-empty")
	}
	model := request.Model
	if model == "" {
		model = p.AskModel
	}
	input := make([]openAIResponseInput, 0, len(request.History)+1)
	for _, turn := range request.History {
		role := strings.TrimSpace(turn.Role)
		text := strings.TrimSpace(turn.Text)
		if (role == "user" || role == "assistant") && text != "" {
			input = append(input, openAIResponseInput{Role: role, Content: text})
		}
	}
	input = append(input, openAIResponseInput{Role: "user", Content: question})

	payload := openAIResponsesRequest{
		Model:        model,
		Instructions: strings.TrimSpace(request.Instructions),
		Input:        input,
	}
	encoded, err := json.Marshal(payload)
	if err != nil {
		return AskResult{}, err
	}
	httpRequest, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		p.urlFor("/v1/responses"),
		bytes.NewReader(encoded),
	)
	if err != nil {
		return AskResult{}, err
	}
	httpRequest.Header.Set("Authorization", "Bearer "+p.APIKey)
	httpRequest.Header.Set("Content-Type", "application/json")

	response, err := p.httpClient().Do(httpRequest)
	if err != nil {
		return AskResult{}, err
	}
	defer response.Body.Close()
	if response.StatusCode >= http.StatusBadRequest {
		return AskResult{}, p.httpError("responses", response)
	}

	var decoded openAIResponsesResponse
	if err := json.NewDecoder(response.Body).Decode(&decoded); err != nil {
		return AskResult{}, err
	}
	answer := strings.TrimSpace(decoded.OutputText)
	if answer == "" {
		answer = strings.TrimSpace(decoded.firstOutputText())
	}
	if request.MaxOutputChars > 0 && len(answer) > request.MaxOutputChars {
		answer = strings.TrimSpace(answer[:request.MaxOutputChars])
	}
	if answer == "" {
		return AskResult{}, fmt.Errorf("openai responses returned empty answer")
	}
	return AskResult{
		Answer:            answer,
		Model:             model,
		ProviderLatencyMS: time.Since(startedAt).Milliseconds(),
	}, nil
}
```

Add helper:

```go
func (r openAIResponsesResponse) firstOutputText() string {
	for _, output := range r.Output {
		for _, content := range output.Content {
			if content.Type == "output_text" && strings.TrimSpace(content.Text) != "" {
				return content.Text
			}
		}
	}
	return ""
}
```

Update missing API key test to call `Ask()` and env default/override tests to include `YOYOPOD_CLOUD_ASK_MODEL`.

- [ ] **Step 7: Dispatch `voice.ask` in worker**

In `workers/voice/go/internal/worker/worker.go`, add case:

```go
case "voice.ask":
	w.startWork(ctx, envelope, w.handleAsk)
```

Add handler:

```go
func (w *Worker) handleAsk(ctx context.Context, envelope protocol.Envelope) {
	var request provider.AskRequest
	if err := decodePayload(envelope.Payload, &request); err != nil {
		w.emitError(envelope, "invalid_payload", err.Error(), false)
		return
	}
	result, err := w.provider.Ask(ctx, request)
	if err != nil || ctx.Err() != nil {
		if isContextCancelled(ctx, err) || ctx.Err() != nil {
			w.emitCancelled(envelope.RequestID, cancellationReason(ctx))
			return
		}
		if provider.IsInvalidPayload(err) {
			w.emitError(envelope, "invalid_payload", err.Error(), false)
			return
		}
		w.emitError(envelope, "provider_error", err.Error(), true)
		return
	}
	w.emitResult(envelope, "voice.ask.result", result)
}
```

- [ ] **Step 8: Run Go tests**

Run:

```bash
Set-Location workers/voice/go
go test ./...
Set-Location ../../..
```

Expected: pass.

- [ ] **Step 9: Commit Go Ask worker**

Run:

```bash
git add workers/voice/go/internal/provider/provider.go workers/voice/go/internal/provider/mock.go workers/voice/go/internal/provider/openai.go workers/voice/go/internal/worker/worker.go workers/voice/go/internal/provider/openai_test.go workers/voice/go/internal/worker/worker_test.go
git commit --no-verify -m "feat: add cloud ask worker command"
```

---

### Task 4: Ask Conversation State

**Files:**
- Create: `yoyopod/integrations/voice/ask_conversation.py`
- Modify: `yoyopod/integrations/voice/__init__.py`
- Test: `tests/integrations/test_voice_runtime.py`

- [ ] **Step 1: Write conversation helper tests**

Add to `tests/integrations/test_voice_runtime.py`:

```python
from yoyopod.integrations.voice.ask_conversation import AskConversationState
from yoyopod.integrations.voice.worker_contract import VoiceWorkerAskTurn


def test_ask_conversation_keeps_bounded_history() -> None:
    state = AskConversationState(max_turns=2, max_text_chars=12)

    state.append("first question is long", "first answer is long")
    state.append("second question", "second answer")
    state.append("third question", "third answer")

    assert state.history_for_worker() == [
        VoiceWorkerAskTurn(role="user", text="second quest"),
        VoiceWorkerAskTurn(role="assistant", text="second answe"),
        VoiceWorkerAskTurn(role="user", text="third questi"),
        VoiceWorkerAskTurn(role="assistant", text="third answer"),
    ]


def test_ask_conversation_detects_exit_phrases() -> None:
    state = AskConversationState()

    assert state.is_exit_request("exit ask")
    assert state.is_exit_request("go back")
    assert state.is_exit_request("stop asking")
    assert not state.is_exit_request("why do birds sing")
```

- [ ] **Step 2: Run helper tests and verify they fail**

Run:

```bash
uv run pytest tests/integrations/test_voice_runtime.py::test_ask_conversation_keeps_bounded_history tests/integrations/test_voice_runtime.py::test_ask_conversation_detects_exit_phrases -q
```

Expected: import failure for `AskConversationState`.

- [ ] **Step 3: Implement `AskConversationState`**

Create `yoyopod/integrations/voice/ask_conversation.py`:

```python
"""Bounded in-memory state for conversational Ask mode."""

from __future__ import annotations

from dataclasses import dataclass, field

from yoyopod.integrations.voice.worker_contract import VoiceWorkerAskTurn


_EXIT_PHRASES = {
    "exit ask",
    "go back",
    "stop asking",
    "stop ask",
    "leave ask",
    "close ask",
}


@dataclass(slots=True)
class AskConversationState:
    """Keep a small local Ask history while the Ask screen is active."""

    max_turns: int = 4
    max_text_chars: int = 480
    _turns: list[tuple[str, str]] = field(default_factory=list)

    def reset(self) -> None:
        self._turns.clear()

    def append(self, question: str, answer: str) -> None:
        question = self._trim(question)
        answer = self._trim(answer)
        if not question or not answer:
            return
        self._turns.append((question, answer))
        if len(self._turns) > self.max_turns:
            self._turns = self._turns[-self.max_turns :]

    def history_for_worker(self) -> list[VoiceWorkerAskTurn]:
        history: list[VoiceWorkerAskTurn] = []
        for question, answer in self._turns:
            history.append(VoiceWorkerAskTurn(role="user", text=question))
            history.append(VoiceWorkerAskTurn(role="assistant", text=answer))
        return history

    def is_exit_request(self, transcript: str) -> bool:
        normalized = " ".join(transcript.lower().strip().split())
        return normalized in _EXIT_PHRASES

    def _trim(self, text: str) -> str:
        normalized = " ".join(text.strip().split())
        return normalized[: max(1, self.max_text_chars)].strip()
```

- [ ] **Step 4: Export the helper**

In `yoyopod/integrations/voice/__init__.py`, add:

```python
"AskConversationState": ("yoyopod.integrations.voice.ask_conversation", "AskConversationState"),
```

Add `AskConversationState` to `TYPE_CHECKING` imports and `__all__`.

- [ ] **Step 5: Run helper tests**

Run:

```bash
uv run pytest tests/integrations/test_voice_runtime.py::test_ask_conversation_keeps_bounded_history tests/integrations/test_voice_runtime.py::test_ask_conversation_detects_exit_phrases -q
```

Expected: pass.

- [ ] **Step 6: Commit conversation helper**

Run:

```bash
git add yoyopod/integrations/voice/ask_conversation.py yoyopod/integrations/voice/__init__.py tests/integrations/test_voice_runtime.py
git commit --no-verify -m "feat: add ask conversation state"
```

---

### Task 5: Runtime Conversational Ask Mode

**Files:**
- Modify: `yoyopod/integrations/voice/runtime.py`
- Modify: `yoyopod/core/bootstrap/screens_boot.py`
- Test: `tests/integrations/test_voice_runtime.py`

- [ ] **Step 1: Write runtime tests for conversational Ask**

Add to `tests/integrations/test_voice_runtime.py`:

```python
from yoyopod.integrations.voice.worker_contract import VoiceWorkerAskResult, VoiceWorkerAskTurn


class _FakeAskClient:
    def __init__(self, answer: str = "Clouds are made of tiny water drops.") -> None:
        self.answer = answer
        self.calls: list[dict[str, object]] = []
        self.is_available = True

    def ask(
        self,
        *,
        question: str,
        history: list[VoiceWorkerAskTurn],
        model: str,
        instructions: str,
        max_output_chars: int,
        cancel_event: threading.Event | None = None,
    ) -> VoiceWorkerAskResult:
        self.calls.append(
            {
                "question": question,
                "history": history,
                "model": model,
                "instructions": instructions,
                "max_output_chars": max_output_chars,
                "cancel_event": cancel_event,
            }
        )
        return VoiceWorkerAskResult(answer=self.answer, model=model)
```

Add first-turn test:

```python
def test_voice_runtime_begin_ask_answers_without_executing_command(tmp_path: Path) -> None:
    audio_path = tmp_path / "ask.wav"
    audio_path.write_bytes(b"RIFF")
    ask_client = _FakeAskClient()
    outcomes: list[VoiceCommandOutcome] = []

    class _QuestionVoiceService(_FakeVoiceService):
        def capture_audio(self, _request) -> VoiceCaptureResult:
            return VoiceCaptureResult(audio_path=audio_path, recorded=True)

        def transcribe(self, path: Path, *, cancel_event=None) -> VoiceTranscript:
            assert path == audio_path
            return VoiceTranscript(text="why is the sky blue", confidence=1.0)

    class _CommandExecutor:
        def execute(self, transcript: str) -> VoiceCommandOutcome:
            raise AssertionError(f"command executor should not run for Ask: {transcript}")

    service = _QuestionVoiceService("why is the sky blue")
    coordinator = VoiceRuntimeCoordinator(
        context=None,
        settings_resolver=VoiceSettingsResolver(
            context=None,
            settings_provider=lambda: VoiceSettings(
                mode="cloud",
                ai_requests_enabled=True,
                cloud_worker_ask_model="gpt-4.1-mini",
                cloud_worker_ask_instructions="Answer for a child.",
                cloud_worker_ask_max_history_turns=4,
                cloud_worker_ask_max_response_chars=480,
            ),
        ),
        command_executor=_CommandExecutor(),
        voice_service_factory=lambda _settings: service,
        ask_client=ask_client,
        output_player=_FakeOutputPlayer(),
    )
    coordinator.bind(
        state_listener=None,
        outcome_listener=outcomes.append,
        dispatcher=lambda callback: callback(),
    )

    coordinator.begin_ask(async_capture=False)

    assert ask_client.calls[0]["question"] == "why is the sky blue"
    assert ask_client.calls[0]["history"] == []
    assert outcomes[-1] == VoiceCommandOutcome(
        "Answer",
        "Clouds are made of tiny water drops.",
        should_speak=True,
        auto_return=False,
    )
    assert not audio_path.exists()
```

Add history test:

```python
def test_voice_runtime_ask_keeps_history_between_turns(tmp_path: Path) -> None:
    paths = [tmp_path / "first.wav", tmp_path / "second.wav"]
    for path in paths:
        path.write_bytes(b"RIFF")
    transcripts = ["what is rain", "why does it fall"]
    ask_client = _FakeAskClient(answer="Rain comes from clouds.")

    class _TwoTurnVoiceService(_FakeVoiceService):
        def capture_audio(self, _request) -> VoiceCaptureResult:
            return VoiceCaptureResult(audio_path=paths.pop(0), recorded=True)

        def transcribe(self, _path: Path, *, cancel_event=None) -> VoiceTranscript:
            return VoiceTranscript(text=transcripts.pop(0), confidence=1.0)

    coordinator = VoiceRuntimeCoordinator(
        context=None,
        settings_resolver=VoiceSettingsResolver(
            context=None,
            settings_provider=lambda: VoiceSettings(
                mode="cloud",
                ai_requests_enabled=True,
                cloud_worker_ask_model="gpt-4.1-mini",
            ),
        ),
        command_executor=VoiceCommandExecutor(context=None),
        voice_service_factory=lambda _settings: _TwoTurnVoiceService(""),
        ask_client=ask_client,
        output_player=_FakeOutputPlayer(),
    )
    coordinator.bind(state_listener=None, dispatcher=lambda callback: callback())

    coordinator.begin_ask(async_capture=False)
    coordinator.begin_ask(async_capture=False)

    assert ask_client.calls[1]["history"] == [
        VoiceWorkerAskTurn(role="user", text="what is rain"),
        VoiceWorkerAskTurn(role="assistant", text="Rain comes from clouds."),
    ]
```

Add disabled/offline/cancel tests:

```python
def test_voice_runtime_ask_disabled_does_not_capture() -> None:
    service = _FakeVoiceService("why")
    coordinator = VoiceRuntimeCoordinator(
        context=None,
        settings_resolver=VoiceSettingsResolver(
            context=None,
            settings_provider=lambda: VoiceSettings(ai_requests_enabled=False),
        ),
        command_executor=VoiceCommandExecutor(context=None),
        voice_service_factory=lambda _settings: service,
        ask_client=_FakeAskClient(),
        output_player=_FakeOutputPlayer(),
    )

    coordinator.begin_ask(async_capture=False)

    assert service.capture_calls == 0
    assert coordinator.state.headline == "Ask Off"
```

```python
def test_voice_runtime_ask_unavailable_reports_cloud_unavailable() -> None:
    ask_client = _FakeAskClient()
    ask_client.is_available = False
    coordinator = VoiceRuntimeCoordinator(
        context=None,
        settings_resolver=VoiceSettingsResolver(
            context=None,
            settings_provider=lambda: VoiceSettings(mode="cloud", ai_requests_enabled=True),
        ),
        command_executor=VoiceCommandExecutor(context=None),
        voice_service_factory=lambda _settings: _FakeVoiceService("why"),
        ask_client=ask_client,
        output_player=_FakeOutputPlayer(),
    )

    coordinator.begin_ask(async_capture=False)

    assert coordinator.state.headline == "Ask Offline"
    assert "cannot reach Ask" in coordinator.state.body
```

- [ ] **Step 2: Run runtime tests and verify they fail**

Run:

```bash
uv run pytest tests/integrations/test_voice_runtime.py -q
```

Expected: failure because `VoiceRuntimeCoordinator` has no `ask_client` parameter or `begin_ask()` method.

- [ ] **Step 3: Add Ask client protocol and constructor dependency**

In `yoyopod/integrations/voice/runtime.py`, import:

```python
from yoyopod.integrations.voice.ask_conversation import AskConversationState
from yoyopod.integrations.voice.worker_contract import VoiceWorkerAskResult, VoiceWorkerAskTurn
```

Add `Protocol` import and protocol:

```python
class _AskClient(Protocol):
    @property
    def is_available(self) -> bool:
        """Return whether cloud Ask can accept requests."""

    def ask(
        self,
        *,
        question: str,
        history: list[VoiceWorkerAskTurn],
        model: str,
        instructions: str,
        max_output_chars: int,
        cancel_event: threading.Event | None = None,
    ) -> VoiceWorkerAskResult:
        """Return one conversational Ask answer."""
```

Extend constructor:

```python
ask_client: _AskClient | None = None,
```

Store fields:

```python
self._ask_client = ask_client
self._ask_conversation = AskConversationState()
```

- [ ] **Step 4: Split entry behavior**

Update `begin_entry_cycle()`:

```python
def begin_entry_cycle(self, *, quick_command: bool, async_capture: bool) -> None:
    """Start the default Ask entry behavior for the current mode."""

    self.reset_to_idle()
    if quick_command:
        self.begin_ptt_capture()
        return
    self.begin_ask(async_capture=async_capture)
```

In `reset_to_idle()`, do not reset conversation. Reset history on screen exit by adding a method:

```python
def reset_conversation(self) -> None:
    """Drop Ask history when the Ask screen exits."""

    self._ask_conversation.reset()
```

- [ ] **Step 5: Implement `begin_ask()`**

Add method:

```python
def begin_ask(self, *, async_capture: bool) -> None:
    """Start one record-transcribe-conversational-answer cycle."""

    if self._state.capture_in_flight:
        return
    voice_service, settings = self._voice_service_with_settings()
    readiness_error = self._prepare_ask_capture(
        voice_service=voice_service,
        settings=settings,
    )
    if readiness_error is not None:
        self._apply_outcome(readiness_error)
        return

    self._ask_conversation.max_turns = max(1, settings.cloud_worker_ask_max_history_turns)
    self._ask_conversation.max_text_chars = max(1, settings.cloud_worker_ask_max_response_chars)
    generation = self._next_generation()
    cancel_event = threading.Event()
    self._active_capture_cancel = cancel_event
    self._set_state(
        "listening",
        "Listening",
        "Ask your question...",
        capture_in_flight=True,
        generation=generation,
    )
    if async_capture:
        threading.Thread(
            target=self._run_ask_cycle,
            args=(voice_service, settings, generation, cancel_event),
            daemon=True,
            name="VoiceRuntimeAsk",
        ).start()
        return
    self._run_ask_cycle(voice_service, settings, generation, cancel_event)
```

Add readiness helper:

```python
def _prepare_ask_capture(
    self,
    *,
    voice_service: VoiceManager,
    settings: VoiceSettings,
) -> VoiceCommandOutcome | None:
    if self._context is not None and not self._context.voice.ai_requests_enabled:
        return VoiceCommandOutcome("Ask Off", "Turn Ask on in Setup first.", should_speak=False)
    if not settings.ai_requests_enabled:
        return VoiceCommandOutcome("Ask Off", "Turn Ask on in Setup first.", should_speak=False)
    if self._context is not None and self._context.voice.mic_muted:
        return VoiceCommandOutcome("Mic Muted", "Unmute the microphone first.", should_speak=False)
    if self._ask_client is None or not self._ask_client.is_available:
        return VoiceCommandOutcome(
            "Ask Offline",
            "I cannot reach Ask right now. I can still help with music, calls, and volume.",
            should_speak=False,
            auto_return=False,
        )
    if not voice_service.capture_available():
        return VoiceCommandOutcome("Mic Unavailable", "Voice capture is not ready on this device.", should_speak=False)
    if not voice_service.stt_available():
        return VoiceCommandOutcome(
            "Speech Offline",
            "Cloud speech is unavailable. Local controls still work.",
            should_speak=False,
            auto_return=False,
        )
    return None
```

- [ ] **Step 6: Implement `_run_ask_cycle()`**

Add method:

```python
def _run_ask_cycle(
    self,
    voice_service: VoiceManager,
    settings: VoiceSettings,
    generation: int,
    cancel_event: threading.Event,
) -> None:
    self._play_attention_tone()
    request = VoiceCaptureRequest(
        mode="ask",
        timeout_seconds=4.0,
        cancel_event=cancel_event,
    )
    capture_result = voice_service.capture_audio(request)
    if cancel_event.is_set():
        if capture_result.audio_path is not None:
            capture_result.audio_path.unlink(missing_ok=True)
        return
    if capture_result.audio_path is None:
        self._dispatch_ask_outcome(
            VoiceCommandOutcome("No Speech", "I did not catch that.", should_speak=False, auto_return=False),
            generation=generation,
        )
        return

    try:
        transcript = voice_service.transcribe(capture_result.audio_path, cancel_event=cancel_event)
    except Exception as exc:
        logger.warning("Ask transcription failed: {}", exc)
        self._dispatch_ask_outcome(
            VoiceCommandOutcome("Mic Unavailable", "The Pi microphone input is busy or unavailable.", should_speak=False, auto_return=False),
            generation=generation,
        )
        return
    finally:
        capture_result.audio_path.unlink(missing_ok=True)

    question = transcript.text.strip()
    if cancel_event.is_set() or generation != self._state.generation:
        return
    if not question:
        self._dispatch_ask_outcome(
            VoiceCommandOutcome("No Speech", "I did not catch that.", should_speak=False, auto_return=False),
            generation=generation,
        )
        return
    if self._ask_conversation.is_exit_request(question):
        self._dispatch_ask_outcome(
            VoiceCommandOutcome("Ask", "Going back.", should_speak=False, route_name="back", auto_return=False),
            generation=generation,
        )
        return

    self._dispatch(lambda: self._set_state("thinking", "Thinking", "Finding an answer...", capture_in_flight=True))
    ask_client = self._ask_client
    if ask_client is None:
        self._dispatch_ask_outcome(
            VoiceCommandOutcome("Ask Offline", "I cannot reach Ask right now. I can still help with music, calls, and volume.", should_speak=False, auto_return=False),
            generation=generation,
        )
        return
    try:
        result = ask_client.ask(
            question=question,
            history=self._ask_conversation.history_for_worker(),
            model=settings.cloud_worker_ask_model,
            instructions=settings.cloud_worker_ask_instructions,
            max_output_chars=settings.cloud_worker_ask_max_response_chars,
            cancel_event=cancel_event,
        )
    except Exception as exc:
        logger.warning("Ask request failed: {}", exc)
        self._dispatch_ask_outcome(
            VoiceCommandOutcome("Ask Offline", "I cannot reach Ask right now. I can still help with music, calls, and volume.", should_speak=False, auto_return=False),
            generation=generation,
        )
        return
    if cancel_event.is_set() or generation != self._state.generation:
        return
    self._ask_conversation.append(question, result.answer)
    self._dispatch_ask_outcome(
        VoiceCommandOutcome("Answer", result.answer, should_speak=True, auto_return=False),
        generation=generation,
    )
```

Add dispatcher:

```python
def _dispatch_ask_outcome(self, outcome: VoiceCommandOutcome, *, generation: int) -> None:
    def apply_result() -> None:
        if generation != self._state.generation:
            return
        self._active_capture_cancel = None
        self._apply_outcome(outcome)

    self._dispatch(apply_result)
```

- [ ] **Step 7: Run runtime tests**

Run:

```bash
uv run pytest tests/integrations/test_voice_runtime.py -q
```

Expected: pass.

- [ ] **Step 8: Commit runtime Ask mode**

Run:

```bash
git add yoyopod/integrations/voice/runtime.py yoyopod/core/bootstrap/screens_boot.py tests/integrations/test_voice_runtime.py
git commit --no-verify -m "feat: add conversational ask runtime"
```

---

### Task 6: Ask Screen Mode Selection

**Files:**
- Modify: `yoyopod/ui/screens/navigation/ask/__init__.py`
- Test: `tests/ui/test_screen_routing.py`

- [ ] **Step 1: Extend the stub runtime in screen routing tests**

In `_StubVoiceRuntime` inside `tests/ui/test_screen_routing.py`, add:

```python
self.begin_ask_calls: list[bool] = []
self.reset_conversation_calls = 0
```

Add methods:

```python
def begin_ask(self, *, async_capture: bool) -> None:
    self.begin_ask_calls.append(async_capture)

def reset_conversation(self) -> None:
    self.reset_conversation_calls += 1
```

- [ ] **Step 2: Write Ask screen mode tests**

Add tests:

```python
def test_ask_screen_select_uses_conversation_mode_by_default() -> None:
    runtime = _StubVoiceRuntime()
    ask = AskScreen(display=object(), context=AppContext(), voice_runtime=runtime)

    ask.on_select()

    assert runtime.begin_ask_calls == [True]
```

```python
def test_ask_screen_select_uses_command_mode_when_quick_command() -> None:
    runtime = _StubVoiceRuntime()
    ask = AskScreen(display=object(), context=AppContext(), voice_runtime=runtime)
    ask.set_quick_command(True)

    ask.on_select()

    assert runtime.begin_entry_cycle_calls == []
    assert runtime.begin_ask_calls == []
```

Use the existing `begin_listening` stub and add `begin_listening_calls`:

```python
self.begin_listening_calls: list[bool] = []

def begin_listening(self, *, async_capture: bool) -> None:
    self.begin_listening_calls.append(async_capture)
```

Then assert:

```python
assert runtime.begin_listening_calls == [True]
```

Add exit reset test:

```python
def test_ask_screen_exit_resets_conversation_history() -> None:
    runtime = _StubVoiceRuntime()
    ask = AskScreen(display=object(), context=AppContext(), voice_runtime=runtime)

    ask.exit()

    assert runtime.reset_conversation_calls == 1
```

- [ ] **Step 3: Run screen routing tests and verify they fail**

Run:

```bash
uv run pytest tests/ui/test_screen_routing.py -q
```

Expected: failure because `AskScreen.on_select()` always calls `begin_listening()`, and `exit()` does not reset conversation history.

- [ ] **Step 4: Implement Ask screen mode selection**

In `yoyopod/ui/screens/navigation/ask/__init__.py`, update `on_select()`:

```python
def on_select(self, data=None) -> None:
    """Start command listening or ask again depending on Ask entry mode."""

    if self._quick_command:
        self.voice_runtime.begin_listening(async_capture=self._async_voice_capture)
        return
    self.voice_runtime.begin_ask(async_capture=self._async_voice_capture)
```

In `exit()`, reset conversation:

```python
self.voice_runtime.reset_conversation()
```

Update `_screen_summary()`:

```python
if self._quick_command:
    return "You are on quick Ask. Say a direct command now."
return "You are on Ask. Ask a question, or go back to exit."
```

Update `_HINT_TEXT`:

```python
_HINT_TEXT = "Ask a question. Use the quick button for calls, music, volume, and screen reading."
```

- [ ] **Step 5: Run screen routing tests**

Run:

```bash
uv run pytest tests/ui/test_screen_routing.py -q
```

Expected: pass.

- [ ] **Step 6: Commit Ask screen mode selection**

Run:

```bash
git add yoyopod/ui/screens/navigation/ask/__init__.py tests/ui/test_screen_routing.py
git commit --no-verify -m "feat: split ask screen conversation mode"
```

---

### Task 7: Enrich Deterministic Command Grammar

**Files:**
- Modify: `yoyopod/integrations/voice/commands.py`
- Test: `tests/integrations/test_voice_service.py`
- Test: `tests/integrations/test_voice_runtime.py`
- Test: `tests/ui/test_screen_routing.py`

- [ ] **Step 1: Write parser tests for new phrases**

Add to `tests/integrations/test_voice_service.py`:

```python
def test_match_voice_command_accepts_family_call_variations() -> None:
    phrases = [
        "call mama",
        "call mommy",
        "call my mama",
        "please call my mom",
        "ring mama",
        "phone mom",
        "call daddy",
        "call papa",
        "ring papa",
    ]

    for phrase in phrases:
        match = match_voice_command(phrase)
        assert match.intent is VoiceCommandIntent.CALL_CONTACT
        assert match.contact_name
```

```python
def test_match_voice_command_accepts_music_and_volume_variations() -> None:
    for phrase in ["play a song", "play songs", "put on music", "start songs", "play kids music"]:
        assert match_voice_command(phrase).intent is VoiceCommandIntent.PLAY_MUSIC

    for phrase in ["louder", "make it louder", "too quiet"]:
        assert match_voice_command(phrase).intent is VoiceCommandIntent.VOLUME_UP

    for phrase in ["quieter", "make it quieter", "too loud"]:
        assert match_voice_command(phrase).intent is VoiceCommandIntent.VOLUME_DOWN
```

```python
def test_match_voice_command_accepts_screen_and_mic_variations() -> None:
    for phrase in ["read this", "what is on the screen", "tell me what is on the screen"]:
        assert match_voice_command(phrase).intent is VoiceCommandIntent.READ_SCREEN

    for phrase in ["turn off the mic", "turn off microphone"]:
        assert match_voice_command(phrase).intent is VoiceCommandIntent.MUTE_MIC

    for phrase in ["turn on the mic", "turn on microphone"]:
        assert match_voice_command(phrase).intent is VoiceCommandIntent.UNMUTE_MIC
```

- [ ] **Step 2: Run parser tests and verify they fail**

Run:

```bash
uv run pytest tests/integrations/test_voice_service.py::test_match_voice_command_accepts_family_call_variations tests/integrations/test_voice_service.py::test_match_voice_command_accepts_music_and_volume_variations tests/integrations/test_voice_service.py::test_match_voice_command_accepts_screen_and_mic_variations -q
```

Expected: failure for phrases not in the current grammar.

- [ ] **Step 3: Expand grammar templates**

In `yoyopod/integrations/voice/commands.py`, update call examples:

```python
examples=(
    "call mom",
    "call dad",
    "please call mama",
    "call my mama",
    "call mommy",
    "call daddy",
    "call papa",
),
```

Update `PLAY_MUSIC` trigger phrases:

```python
"play a song",
"play songs",
"put on music",
"start songs",
"play kids music",
```

Update `VOLUME_UP` trigger phrases:

```python
"louder",
"make it louder",
"too quiet",
```

Update `VOLUME_DOWN` trigger phrases:

```python
"quieter",
"make it quieter",
"too loud",
```

Update `READ_SCREEN` trigger phrases:

```python
"read this",
"what is on the screen",
"tell me what is on the screen",
```

Update mic trigger phrases:

```python
"turn off the mic",
"turn off microphone",
```

```python
"turn on the mic",
"turn on microphone",
```

If `ring mama` and `phone mom` fail because the slot extraction trims incorrectly, update `_SLOT_FILLER_TOKENS` with:

```python
_SLOT_FILLER_TOKENS = frozenset({"a", "an", "the", "to", "for", "my", "please", "now"})
```

Keep new phrases within existing intents. Do not add pause/next/previous commands in this task.

- [ ] **Step 4: Run parser and runtime command tests**

Run:

```bash
uv run pytest tests/integrations/test_voice_service.py tests/integrations/test_voice_runtime.py tests/ui/test_screen_routing.py -q
```

Expected: pass.

- [ ] **Step 5: Commit command grammar enrichment**

Run:

```bash
git add yoyopod/integrations/voice/commands.py tests/integrations/test_voice_service.py tests/integrations/test_voice_runtime.py tests/ui/test_screen_routing.py
git commit --no-verify -m "feat: enrich voice command phrases"
```

---

### Task 8: Documentation, Full Verification, And Pi Dev Lane Validation

**Files:**
- Modify: `docs/CLOUD_VOICE_WORKER.md`

- [ ] **Step 1: Update cloud setup docs**

In `docs/CLOUD_VOICE_WORKER.md`, replace the env block with:

```bash
OPENAI_API_KEY=sk-...
YOYOPOD_VOICE_MODE=cloud
YOYOPOD_VOICE_WORKER_ENABLED=true
YOYOPOD_VOICE_WORKER_PROVIDER=openai
YOYOPOD_STT_BACKEND=cloud-worker
YOYOPOD_TTS_BACKEND=cloud-worker
YOYOPOD_CLOUD_TTS_MODEL=gpt-4o-mini-tts
YOYOPOD_CLOUD_TTS_VOICE=coral
YOYOPOD_CLOUD_TTS_INSTRUCTIONS="Speak warmly and calmly for a child. Use simple words, friendly pacing, and brief answers. Avoid scary emphasis."
YOYOPOD_CLOUD_ASK_MODEL=gpt-4.1-mini
YOYOPOD_CLOUD_ASK_TIMEOUT_SECONDS=12
YOYOPOD_CLOUD_ASK_MAX_HISTORY_TURNS=4
YOYOPOD_CLOUD_ASK_MAX_RESPONSE_CHARS=480
```

Add this paragraph below the env block:

```markdown
OpenAI requires disclosure that TTS output is AI-generated. YoYoPod should be treated as an AI voice device whenever cloud TTS is enabled.
```

Add a manual Ask validation section:

```markdown
## Ask App Smoke Test

1. Open Ask from the hub, not quick PTT.
2. Ask "why is the sky blue?"
3. Confirm the screen shows an answer and the speaker uses the configured cloud voice.
4. Tap/select Ask again and ask "what is rain?"
5. Confirm the second answer works without leaving Ask.
6. Press Back or hold Back and confirm Ask exits and no stale answer plays.
7. Use quick PTT for "call mama", "play music", and "make it louder" to confirm commands still use command mode.
```

- [ ] **Step 2: Run full local verification**

Run from repo root:

```bash
uv run python scripts/quality.py gate
uv run pytest -q
```

Expected:

```text
[quality] result=passed
1411+ passed, 22 skipped
```

The exact pass count may increase because new tests were added.

- [ ] **Step 3: Run Go verification**

Run:

```bash
Set-Location workers/voice/go
go test ./...
Set-Location ../../..
```

Expected: all Go packages pass.

- [ ] **Step 4: Commit docs and final local verification context**

Run:

```bash
git add docs/CLOUD_VOICE_WORKER.md
git commit --no-verify -m "docs: document cloud ask setup"
```

- [ ] **Step 5: Run required pre-push gates**

Run:

```bash
uv run python scripts/quality.py gate
uv run pytest -q
```

Expected:

```text
[quality] result=passed
1411+ passed, 22 skipped
```

- [ ] **Step 6: Push branch**

Run:

```bash
git push origin codex/runtime-hybrid-phase-2
```

Expected: branch updates PR #386.

- [ ] **Step 7: Deploy to Pi dev lane**

Run:

```bash
yoyopod remote mode activate dev
yoyopod remote sync --branch codex/runtime-hybrid-phase-2 --clean-native
```

Expected: dev checkout syncs and `yoyopod-dev.service` restarts.

- [ ] **Step 8: Validate Pi service and worker logs**

Run:

```bash
yoyopod remote mode status
yoyopod remote status
yoyopod remote logs --service yoyopod-dev.service --lines 160
```

Expected log evidence:

```text
Cloud voice worker ready: provider=openai
Voice listen result applying
Voice outcome applied
Cloud worker speech synthesis completed
```

- [ ] **Step 9: Hardware functional smoke**

On the device:

```text
Open Ask from the hub.
Ask: why is the sky blue?
Ask a second question without leaving Ask: what is rain?
Exit Ask with Back.
Use quick PTT: call mama.
Use quick PTT: play music.
Use quick PTT: make it louder.
```

Expected:

```text
Ask stays open across Q&A turns.
Ask answers are spoken with the configured voice.
Back exits Ask and no stale answer plays.
Quick PTT still executes deterministic commands.
```

Capture final logs:

```bash
yoyopod remote logs --service yoyopod-dev.service --lines 240
```

---

## Self-Review Checklist

- Spec coverage: covered TTS config, Ask conversational mode, Go worker boundary, cancellation, history, command enrichment, docs, full tests, and Pi validation.
- Type consistency: Python Ask datatypes are `VoiceWorkerAskTurn` and `VoiceWorkerAskResult`; Go Ask datatypes are `AskTurn`, `AskRequest`, and `AskResult`.
- Protocol consistency: request command is `voice.ask`; result type is `voice.ask.result`; cancellation uses existing fixed `voice.cancel`.
- Scope control: no web search, no parent controls, no AI-driven device actions, no new music playback intents.
- Verification: each task has focused tests, a commit, and final local plus Pi validation.
