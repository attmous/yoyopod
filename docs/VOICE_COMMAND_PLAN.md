# Voice Command Plan

**Status:** Transitional design record, partly stale relative to the current `Ask` flow

> Current note: this document captures the original design direction for local voice control. The current codebase now uses a unified `AskScreen` instead of the earlier split `Voice Commands` and `AI Requests` menu shape described below. Keep using this file for design context and future direction, but trust the current code and `docs/SYSTEM_ARCHITECTURE.md` for what exists on `main`.

> Read this as a direction and constraint document, not as proof that every flow, menu shape, or setting below is what ships today.

## Goal

Add local voice commands and spoken device responses to YoyoPod using:

- `vosk` small model for offline speech-to-text
- `espeak-ng` for offline text-to-speech

This phase focuses on deterministic local voice control and spoken feedback.
AI-generated responses remain a future feature and should stay behind a separate
Ask flow boundary.

## Product Shape

The `Ask` menu should split into two explicit sub-items:

- `Voice Commands`
- `AI Requests`

This keeps deterministic command handling separate from future conversational AI.

## Scope

### In Scope

- Local STT with Vosk small
- Local TTS with `espeak-ng`
- Spoken confirmations and basic screen reading
- Voice-command execution for selected device actions
- Settings for voice-related behavior
- Ask flow split into `Voice Commands` and `AI Requests`
- AI Requests placeholder response only

### Out of Scope

- Full conversational AI responses
- Cloud STT/TTS
- Wake-word or always-listening mode
- Fuzzy natural-language assistant behavior beyond bounded command parsing

## User Flows

### Ask -> Voice Commands

1. User enters `Ask`
2. User selects `Voice Commands`
3. Device starts bounded listening flow
4. STT converts speech to text
5. Intent parser resolves a direct command
6. Device executes the command
7. TTS confirms the result

Examples:

- `call mom`
- `call dad`
- `volume up`
- `volume down`
- `mute mic`
- `unmute mic`
- `read screen`

### Ask -> AI Requests

1. User enters `Ask`
2. User selects `AI Requests`
3. Device starts the same STT capture flow
4. Transcript is classified as AI-path input by menu context, not by intent ambiguity
5. Device returns a placeholder spoken response such as:
   `AI responses are not available yet`

This keeps the future AI path visible without mixing it into direct command execution.

## Settings Requirements

Add device settings for:

- `voice_commands_enabled`
- `screen_read_enabled`
- `output_volume`
- `mic_muted`

Possible later additions:

- `tts_voice`
- `tts_rate`
- `stt_timeout_seconds`

## Command Set

The first implementation should stay intentionally small and deterministic.

### Calling

- `call mom`
- `call dad`
- `call <contact>`

Behavior:

- Prefer exact contact-name match first
- If no exact match exists, fail with spoken feedback
- Fuzzy matching can be added later, but not in the first pass

### Audio

- `volume up`
- `volume down`
- `set volume to <n>`
- `mute mic`
- `unmute mic`

### Device / Accessibility

- `read screen`
- `stop speaking`

Optional later:

- `go home`
- `open talk`
- `open listen`

## Interaction Model

### Voice Commands Mode

- Explicitly invoked from `Ask -> Voice Commands`
- Not always listening
- Should work with the active audio input/output device defaults
- Should provide short spoken confirmations

### Screen Read

Two behaviors are needed:

- automatic read on screen change when enabled
- on-demand `read screen` command

Screen summaries should be short and purpose-built, not full UI dumps.

Examples:

- `Menu. Listen, Talk, Ask, Setup. Talk selected.`
- `Call contacts. Mom selected. Double tap to call.`

## Architecture

### New Service Layer

Add a local voice service boundary with two parts:

- `SpeechToTextService`
- `TextToSpeechService`

Suggested implementation structure:

- `yoyopy/voice/stt.py`
- `yoyopy/voice/tts.py`
- `yoyopy/voice/commands.py`
- `yoyopy/voice/service.py`
- `yoyopy/voice/models.py`

### Backend Requirements

#### STT

- Vosk small model
- Offline transcript capture from current default mic
- Bounded capture window
- Non-blocking integration with app flow where possible

#### TTS

- `espeak-ng`
- Output through current default audio device
- Short responses only in first phase

## Intent Routing

Command parsing should remain deterministic and rule-based.

Suggested stages:

1. normalize transcript
2. match explicit command patterns
3. extract arguments like contact name or numeric volume
4. return a typed command object
5. execute command through app service boundary

Do not route by trying to infer whether a phrase is “AI-like” or “command-like”.
The Ask submenu already decides the mode.

## App Integration

### Ask UI

Update Ask to render two sub-items:

- `Voice Commands`
- `AI Requests`

### Settings UI

Expose:

- screen read on/off
- output volume
- mic mute/unmute
- voice commands on/off

### Audio Integration

- respect current default input/output device
- respect output volume and mic mute state
- keep device-level and app-level volume behavior aligned

### VoIP Integration

Voice commands should be able to trigger contact calling through the existing Talk/VoIP path.

## Implementation Order

### Phase 1

- Add typed config/settings fields
- Add Ask submenu split
- Add TTS backend wrapper for `espeak-ng`
- Add STT backend wrapper for Vosk

### Phase 2

- Add deterministic command parser
- Add command execution for call, volume, mic mute, and screen read
- Add spoken confirmations

### Phase 3

- Add screen-summary hooks for key screens
- Add auto-read on screen change
- Add AI Requests placeholder flow

## Testing Plan

Add unit tests for:

- config parsing and persistence
- Ask menu routing
- transcript-to-command parsing
- command execution dispatch
- screen-summary generation

Keep STT/TTS behind interfaces so tests do not require hardware.

## Dependencies

Expected additions:

- system package: `espeak-ng`
- Python package(s): `vosk`
- local Vosk small model asset or documented install path

Model handling should be explicit:

- document model download/install location
- fail clearly when model is missing

## Branch Plan

This work should go on a new branch created from the current working state so it includes
the already-approved simulation/input fixes.

Suggested branch name:

- `feat/ask-voice-local`

## Open Decisions

- exact first-pass contact matching policy
- whether `set volume to <n>` ships in phase 1 or phase 2
- whether `stop speaking` is required in the first pass
- whether auto-read applies globally or only to selected screens
