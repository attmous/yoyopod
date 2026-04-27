# Kid-Friendly Cloud Ask Design

**Date:** 2026-04-26
**Owner:** Moustafa
**Status:** Draft for review
**Target hardware:** Raspberry Pi Zero 2W
**Depends on:** Go cloud voice worker, runtime worker supervisor, unified Ask screen

---

## 1. Problem

The cloud voice worker now makes YoYoPod's speech-to-text and text-to-speech path viable on Raspberry Pi Zero 2W without keeping the local Vosk model resident. The current Ask experience is still command-oriented: captured transcripts are routed through the local voice command executor, so the Ask app cannot hold an open question-answer loop for a child.

The next step is to split the voice experience into two clear modes:

- A deterministic command mode for quick actions like calling, music, volume, and screen reading.
- A conversational Ask mode where a child can ask questions and receive short spoken answers until they exit the Ask app.

The same work should make cloud TTS sound consistent and child-friendly, and should expand local command phrasing so the device responds naturally to common kid/family language.

---

## 2. Goals

- Keep quick PTT and quick Ask behavior deterministic for device commands.
- Make the normal Ask app a conversational Q&A mode instead of another command entry point.
- Reuse the Go cloud voice worker as the boundary for OpenAI cloud calls.
- Use one stable cloud TTS voice for commands and Ask answers.
- Add child-friendly TTS instructions for spoken output.
- Keep answers short enough for a small handheld device.
- Keep the UI loop responsive while STT, AI answer generation, and TTS are in flight.
- Preserve cancellation and stale-result protection when the child exits Ask or starts another turn.
- Expand local command matching with common phrase variations.
- Add tests for command variations, Ask mode routing, worker protocol, OpenAI request shape, cancellation, and degraded behavior.

---

## 3. Non-goals

- Do not move screen navigation, app state, command execution, or LVGL rendering into Go.
- Do not make arbitrary AI answers control the device.
- Do not use cloud web search in the first Ask implementation.
- Do not implement parent profiles, content allowlists, or remote parental controls in this slice.
- Do not guarantee child safety solely through prompting. Prompting reduces risk but is not a hard safety boundary.
- Do not make the device continuously hot-mic after every answer. The child should intentionally start each new Ask turn.
- Do not remove local Vosk/espeak support in this change.
- Do not expand VoIP behavior as part of Ask mode.

---

## 4. Design Decision

Use the existing Go cloud voice worker for Ask AI.

The worker should gain a new protocol command:

```text
voice.ask
  -> voice.ask.result
```

The Python supervisor remains responsible for UI state, conversation state, command execution, cancellation policy, local feedback, and TTS playback. The Go worker remains responsible for cloud provider calls, request deadlines, provider errors, and response parsing.

This keeps cloud I/O out of the Python UI path and keeps all OpenAI-specific HTTP behavior behind one sidecar boundary.

---

## 5. TTS Voice And Style

The current cloud worker already supports:

- `YOYOPOD_CLOUD_TTS_MODEL`
- `YOYOPOD_CLOUD_TTS_VOICE`
- `YOYOPOD_CLOUD_TTS_INSTRUCTIONS`

OpenAI's audio speech endpoint supports `gpt-4o-mini-tts`, voice selection, and an `instructions` field for models that support style control. The API reference currently lists built-in voices including `alloy`, `ash`, `ballad`, `coral`, `echo`, `fable`, `onyx`, `nova`, `sage`, `shimmer`, `verse`, `marin`, and `cedar`.

Recommended initial cloud TTS config:

```bash
YOYOPOD_CLOUD_TTS_MODEL=gpt-4o-mini-tts
YOYOPOD_CLOUD_TTS_VOICE=coral
YOYOPOD_CLOUD_TTS_INSTRUCTIONS="Speak warmly and calmly for a child. Use simple words, friendly pacing, and brief answers. Avoid scary emphasis."
```

`coral` is only the initial default for testing. The voice must remain configurable because the final choice should be based on listening tests on the YoYoPod speaker.

All cloud TTS paths should use the same configured voice by default. Command acknowledgements and Ask answers may use different instruction text in the future, but they should not randomly change voices.

The setup documentation should keep the OpenAI API key and cloud mode instructions, and should mention that OpenAI requires disclosure that TTS voices are AI-generated.

References:

- https://platform.openai.com/docs/guides/text-to-speech
- https://platform.openai.com/docs/api-reference/audio/createTranscription.class

---

## 6. Ask Mode UX

The existing Ask screen has enough state to support the split:

- `quick_command=True`: one-shot command mode.
- `quick_command=False`: conversational Ask mode.

### Command mode

Command mode remains for quick PTT and quick Ask entry.

Flow:

```text
PTT / quick Ask
  -> attention tone
  -> capture speech
  -> transcribe
  -> execute local command
  -> optionally speak acknowledgement
  -> auto-return
```

Examples:

- "call mama"
- "play music"
- "make it louder"
- "read the screen"

Unknown command behavior should stay deterministic. It should not silently fall into open AI Q&A, because that would make a quick device command mode unpredictable.

### Conversational Ask mode

Opening the Ask app from navigation enters conversational mode.

Flow:

```text
Ask app opens
  -> prompt/listening state
  -> capture child question
  -> transcribe
  -> send question + bounded history to voice.ask
  -> show answer text on screen
  -> request cloud TTS with configured voice
  -> play spoken answer
  -> stay in Ask reply/ready state
  -> child taps/selects to ask another question, or backs out to exit
```

The app should not automatically start listening again after TTS finishes. That avoids accidental recordings after the answer and keeps turn-taking explicit.

Reserved local exits in Ask mode:

- Physical back exits.
- One-button hold exits, following the existing one-button navigation pattern.
- Spoken phrases like "exit ask", "go back", or "stop asking" may exit Ask before sending a cloud AI request.

Other device commands should stay in command mode. For example, "call mama" inside conversational Ask should be treated as a question or rejected as "Use the quick button for device commands", rather than placing a call from a free-form AI context.

---

## 7. Ask AI Behavior

The Ask assistant should be short, child-friendly, and honest about uncertainty.

Initial system/developer instruction:

```text
You are YoYoPod's friendly Ask helper for a child using a small handheld audio device.
Answer in simple language a child can understand.
Keep answers to 1-3 short sentences unless the child asks for a story.
Be warm, calm, and encouraging.
Do not use scary detail.
Do not ask for private information.
For medical, legal, safety, emergency, or adult topics, give a brief safe answer and say to ask a grown-up.
If you are unsure, say so simply.
Do not claim to browse the internet or know live facts.
```

Recommended initial model:

```bash
YOYOPOD_CLOUD_ASK_MODEL=gpt-4.1-mini
```

Reasoning:

- The task is simple, bounded Q&A.
- Official model docs describe `gpt-4.1-mini` as low latency without a reasoning step.
- The model remains configurable so testing can switch to `gpt-5-mini` if answer quality is worth any added latency.

References:

- https://platform.openai.com/docs/models/gpt-4.1-mini
- https://platform.openai.com/docs/models/gpt-5-mini
- https://platform.openai.com/docs/api-reference/responses/retrieve

---

## 8. Conversation State

Conversation state should live in Python, not in the OpenAI conversation store.

Python should keep a bounded in-memory history while the Ask screen is active:

- Last 4 user/assistant turns by default.
- Maximum transcript characters per user turn.
- Maximum answer characters per assistant turn.
- Reset history when the child exits Ask.
- Reset history when the app restarts.

This keeps privacy and lifecycle behavior local and obvious. It also avoids hidden server-side state becoming the source of unexpected replies after restarts, retries, or cancellations.

The Go worker should receive the already-bounded prompt input and return one answer. It should not own the conversation policy.

---

## 9. Worker Protocol

Add `voice.ask` to the fixed voice protocol.

Request envelope:

```json
{
  "kind": "command",
  "type": "voice.ask",
  "request_id": "ask-123",
  "payload": {
    "question": "why is the sky blue",
    "history": [
      {"role": "user", "text": "what is rain"},
      {"role": "assistant", "text": "Rain is water falling from clouds."}
    ],
    "model": "gpt-4.1-mini",
    "instructions": "child-friendly Ask prompt",
    "max_output_chars": 480
  }
}
```

Result envelope:

```json
{
  "kind": "result",
  "type": "voice.ask.result",
  "request_id": "ask-123",
  "payload": {
    "answer": "The sky looks blue because air scatters blue light from the sun more than other colors.",
    "model": "gpt-4.1-mini"
  }
}
```

Error envelope:

```json
{
  "kind": "error",
  "type": "voice.ask.error",
  "request_id": "ask-123",
  "payload": {
    "code": "provider_unavailable",
    "message": "OpenAI request failed"
  }
}
```

The worker should map provider failures into existing worker error handling patterns. It should use request context cancellation so exiting Ask can cancel an in-flight OpenAI request.

---

## 10. OpenAI Request Shape

The OpenAI provider should use the Responses API for Ask text generation.

Request shape:

```json
{
  "model": "gpt-4.1-mini",
  "instructions": "child-friendly Ask prompt",
  "input": [
    {"role": "user", "content": "what is rain"},
    {"role": "assistant", "content": "Rain is water falling from clouds."},
    {"role": "user", "content": "why is the sky blue"}
  ]
}
```

The provider should parse the returned answer from the response output text. Tests should cover the common `output_text` helper field if present and the structured output array fallback if needed.

The provider should not enable web search or tools in the first version. That keeps answers fast, reduces cost, and avoids live factual claims.

---

## 11. Python Components

Expected Python changes:

- Add Ask-specific settings to the existing voice config model.
- Add `VoiceWorkerClient.ask(...)`.
- Add a small `AskConversationState` helper for bounded in-memory history.
- Add a conversational path to `VoiceRuntimeCoordinator`.
- Keep `handle_transcript()` as the command path for quick command mode.
- Add a separate `handle_ask_question()` or equivalent method for conversational Ask mode.
- Teach `AskScreen` to request command mode or conversational mode explicitly.
- Ensure Ask exit/back cancels any active STT, AI answer, and TTS work.

The command executor should remain local and deterministic. The Ask assistant should not return executable actions.

---

## 12. Configuration

Add or formalize these config fields:

```yaml
assistant:
  ai_requests_enabled: true

worker:
  ask_model: "gpt-4.1-mini"
  ask_timeout_seconds: 12.0
  ask_max_history_turns: 4
  ask_max_response_chars: 480
  ask_instructions: "child-friendly Ask prompt"
```

Environment overrides:

```bash
YOYOPOD_AI_REQUESTS_ENABLED=true
YOYOPOD_CLOUD_ASK_MODEL=gpt-4.1-mini
YOYOPOD_CLOUD_ASK_TIMEOUT_SECONDS=12
YOYOPOD_CLOUD_ASK_MAX_HISTORY_TURNS=4
YOYOPOD_CLOUD_ASK_MAX_RESPONSE_CHARS=480
YOYOPOD_CLOUD_ASK_INSTRUCTIONS="..."
```

The existing setup documentation should include the full cloud voice configuration:

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
```

---

## 13. Command Enrichment

The local grammar should become more tolerant without becoming open-ended.

Initial phrase expansion:

### Calls

- "call mama"
- "call mom"
- "call mommy"
- "call my mama"
- "please call my mom"
- "ring mama"
- "phone mom"
- "call dad"
- "call daddy"
- "call papa"
- "ring papa"

### Music

- "play music"
- "play some music"
- "play a song"
- "play songs"
- "put on music"
- "start music"
- "start songs"
- "play kids music"
- "shuffle music"

### Volume

- "volume up"
- "turn it up"
- "louder"
- "make it louder"
- "too quiet"
- "volume down"
- "turn it down"
- "quieter"
- "make it quieter"
- "too loud"

### Screen Reading

- "read screen"
- "read the screen"
- "read this"
- "what is on the screen"
- "tell me what is on the screen"

### Microphone

- "mute mic"
- "mute microphone"
- "turn off the mic"
- "unmute mic"
- "turn on the mic"

Do not add new executable intents like pause, next, previous, or stop unless the current music service already has stable command hooks. Phrase expansion should be low-risk and tested against the current command surface.

---

## 14. Error Handling

### No speech

Stay in Ask and show a quiet "I did not catch that" state. Do not send an empty question to AI.

### Ask provider timeout

Cancel the worker request and show/speak a short degraded message:

```text
I cannot reach Ask right now. I can still help with music, calls, and volume.
```

### TTS failure after Ask answer

Show the answer text on screen. Do not lose the answer only because TTS failed. Log the TTS failure and keep Ask usable.

### Back or exit during in-flight work

Cancel capture, ask, and speak requests. Ignore stale replies that arrive after the Ask screen has exited or the turn generation changed.

### Worker degraded

Command mode can still use local command matching if STT returns a transcript. Ask mode should show a clear cloud-unavailable state when AI answer generation is not available.

---

## 15. Testing

Required tests:

- Command parser recognizes the new phrase variations.
- Existing command parser behavior does not regress for current phrases.
- AskScreen quick command mode still calls the command path and auto-returns.
- AskScreen normal mode calls the conversational Ask path and stays in Ask after a reply.
- Back/exit cancels in-flight Ask work.
- Stale Ask replies are ignored after a newer turn starts.
- `VoiceWorkerClient.ask()` sends `voice.ask` with deadlines and request IDs.
- Go worker dispatches `voice.ask` and returns `voice.ask.result`.
- OpenAI provider sends Responses API payload with model, instructions, input, and bounded history.
- OpenAI provider maps provider errors into worker errors.
- TTS request still sends the configured voice and instructions.
- Documentation includes the cloud Ask/TTS environment variables.

Hardware validation:

- Deploy to the Pi dev lane.
- Verify quick PTT command mode still handles at least call/music/volume.
- Verify Ask app supports at least three consecutive Q&A turns.
- Verify exiting Ask stops listening and does not speak stale answers.
- Verify TTS uses the configured voice across command acknowledgement and Ask answers.
- Capture logs for STT, Ask, TTS, cancellation, and worker health.

---

## 16. Rollout

Implement behind config gates already used by cloud voice:

- Cloud Ask only runs when cloud worker mode is enabled and `assistant.ai_requests_enabled` is true.
- Local/offline mode keeps current deterministic command behavior.
- If Ask AI fails, the device stays usable for local navigation, music, calls, and supported voice commands.

Suggested sequence:

1. Add protocol and Go provider tests for `voice.ask`.
2. Add Python client/config/conversation tests.
3. Wire AskScreen conversational mode.
4. Enrich command grammar with tests.
5. Update docs and environment setup.
6. Run full local quality/test gates.
7. Deploy and validate on the Pi dev lane.

---

## 17. Open Risks

- Prompting is not a complete child-safety mechanism. This feature is kid-friendly, not a certified child-safety product.
- Cloud latency may make the turn loop feel slow on weak Wi-Fi. The UI must show clear listening/thinking/speaking states.
- Speaker quality may change which TTS voice feels best. Keep the voice configurable and choose after hardware listening tests.
- Same-room background speech can still confuse STT. Ask should require intentional turn starts rather than continuous listening.
- Model availability and pricing can change. Keep model IDs configurable.
