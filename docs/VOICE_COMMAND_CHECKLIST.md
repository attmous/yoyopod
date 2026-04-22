# Voice Command Implementation Checklist

**Status:** Historical implementation checklist, not the current implementation contract

> Current note: this file preserves a working checklist from an earlier branch snapshot. It still contains old branch naming and older design assumptions from that phase. The links below have been normalized to the current repo layout, but the checklist itself remains historical context, not the authoritative map of what ships on `main`.

## Branch

Historical feature branch at the time this checklist was written:

- `feat/ask-voice-local`

That branch note is preserved for context only.

## Goal

Implement local voice commands and spoken feedback for YoyoPod with:

- `vosk` small for offline STT
- `espeak-ng` for offline TTS

Keep conversational AI responses out of scope for now. The `AI Requests` path
should exist in the UI, but only return a placeholder spoken response.

## Actual Integration Points

The file references below were captured at the time of writing. Their links have been normalized to repo-relative paths where possible, but the checklist itself is still historical context rather than the current implementation contract.

### Ask Navigation and Rendering

- [yoyopod/ui/screens/navigation/ask.py](../yoyopod/ui/screens/navigation/ask.py)
- [yoyopod/ui/screens/navigation/lvgl/ask_view.py](../yoyopod/ui/screens/navigation/lvgl/ask_view.py)
- [yoyopod/ui/screens/router.py](../yoyopod/ui/screens/router.py)
- [yoyopod/app.py](../yoyopod/app.py)

### Setup / Device Settings Screen

- [yoyopod/ui/screens/system/power.py](../yoyopod/ui/screens/system/power.py)
- [yoyopod/ui/screens/system/lvgl/power_view.py](../yoyopod/ui/screens/system/lvgl/power_view.py)

### Shared App State

- [yoyopod/core/app_context.py](../yoyopod/core/app_context.py)

### Config Models and Persistence

- [yoyopod/config/models.py](../yoyopod/config/models.py)
- [yoyopod/config/manager.py](../yoyopod/config/manager.py)
- [config/yoyopod_config.yaml](../config/yoyopod_config.yaml)

### Output Volume and Audio

- [yoyopod/core/audio_volume.py](../yoyopod/core/audio_volume.py)
- [docs/AUDIO_STACK.md](AUDIO_STACK.md)

### Contact Calling / VoIP

- [yoyopod/integrations/call/manager.py](../yoyopod/integrations/call/manager.py)
- [yoyopod/config/manager.py](../yoyopod/config/manager.py)
- [config/contacts.yaml](../config/contacts.yaml)

### Tests to Extend

- [tests/config/test_models.py](../tests/config/test_models.py)
- [tests/ui/test_screen_routing.py](../tests/ui/test_screen_routing.py)
- [tests/core/test_audio_volume.py](../tests/core/test_audio_volume.py)
- add new focused voice tests under `tests/integrations/` and `tests/ui/`

## Work Breakdown

### 1. Add Voice Configuration

Files:

- [yoyopod/config/models.py](../yoyopod/config/models.py)
- [config/yoyopod_config.yaml](../config/yoyopod_config.yaml)

Checklist:

- [ ] add a typed `voice` config section
- [ ] add fields for `voice_commands_enabled`
- [ ] add fields for `screen_read_enabled`
- [ ] add fields for `mic_muted`
- [ ] add fields for `tts_backend`, `tts_rate`, and `tts_voice`
- [ ] add fields for `stt_backend`, `vosk_model_path`, and listen timeout
- [ ] keep defaults local/offline and safe

Notes:

- `AppAudioConfig` already holds output-device-related fields
- voice-specific state should not be stuffed into the existing generic `settings` dict only

### 2. Persist and Expose Voice Settings

Files:

- [yoyopod/config/manager.py](../yoyopod/config/manager.py)
- [yoyopod/core/app_context.py](../yoyopod/core/app_context.py)

Checklist:

- [ ] expose getters for new voice settings from config manager
- [ ] add runtime app-context fields for screen read, mic mute, and current voice availability
- [ ] decide which fields are persistent config vs runtime state
- [ ] keep app context in sync during startup

Notes:

- `AppContext.settings` currently contains brightness/sleep/parental controls only
- this is a good time to move voice-related toggles into typed state instead of growing the raw dict

### 3. Add Local Voice Service Layer

Files to add:

- [yoyopod/voice](../yoyopod/voice)
- suggested:
  - `../yoyopod/voice/__init__.py`
  - `../yoyopod/voice/models.py`
  - `../yoyopod/voice/stt.py`
  - `../yoyopod/voice/tts.py`
  - `../yoyopod/voice/service.py`
  - `../yoyopod/integrations/voice/commands.py`

Checklist:

- [ ] define a small typed command/result model
- [ ] wrap `espeak-ng` as a backend service
- [ ] wrap Vosk model loading and bounded capture as an STT service
- [ ] keep backend execution behind interfaces for tests
- [ ] make missing dependency/model failures explicit and non-fatal

Notes:

- first pass should use subprocess-based adapters where practical
- no always-listening mode in this phase

### 4. Split Ask into Two Explicit Flows

Files:

- [yoyopod/ui/screens/navigation/ask.py](../yoyopod/ui/screens/navigation/ask.py)
- [yoyopod/ui/screens/navigation/lvgl/ask_view.py](../yoyopod/ui/screens/navigation/lvgl/ask_view.py)
- [yoyopod/ui/screens/router.py](../yoyopod/ui/screens/router.py)
- [yoyopod/app.py](../yoyopod/app.py)

Checklist:

- [ ] replace the placeholder Ask state machine with two sub-items:
  - `Voice Commands`
  - `AI Requests`
- [ ] render those two options in both PIL and LVGL paths
- [ ] wire selection flow for standard and one-button interaction modes
- [ ] route `AI Requests` to a placeholder result path
- [ ] route `Voice Commands` to the STT command flow

Notes:

- current Ask is a placeholder with fake prompt/response states
- this file is the primary place to reduce ambiguity and give the mode split a real UX

### 5. Add Deterministic Command Parsing

Files:

- [yoyopod/integrations/voice/commands.py](../yoyopod/integrations/voice/commands.py)
- [yoyopod/config/manager.py](../yoyopod/config/manager.py)
- [config/contacts.yaml](../config/contacts.yaml)

Checklist:

- [ ] normalize transcript text
- [ ] parse direct commands:
  - `call mom`
  - `call dad`
  - `call <contact>`
  - `volume up`
  - `volume down`
  - `set volume to <n>`
  - `mute mic`
  - `unmute mic`
  - `read screen`
- [ ] use exact contact-name matching first
- [ ] support `notes` display labels from contacts like `Mama`
- [ ] return typed command objects rather than raw strings

Notes:

- do not classify “AI-like” requests by transcript content
- Ask submenu selection should decide command mode vs AI mode

### 6. Execute Commands Through Existing Services

Files:

- [yoyopod/app.py](../yoyopod/app.py)
- [yoyopod/core/audio_volume.py](../yoyopod/core/audio_volume.py)
- [yoyopod/integrations/call/manager.py](../yoyopod/integrations/call/manager.py)
- [yoyopod/core/app_context.py](../yoyopod/core/app_context.py)

Checklist:

- [ ] connect parsed call commands to existing VoIP call flow
- [ ] connect volume commands to `OutputVolumeController`
- [ ] add mic mute/unmute execution path
- [ ] expose execution results as short TTS-ready messages
- [ ] update app context state after command execution

Notes:

- `VoIPManager.make_call()` already exists
- output volume already has a shared controller; do not duplicate it
- mic mute will likely need a small new service/controller separate from call mute

### 7. Add Device Settings for Voice and Accessibility

Files:

- [yoyopod/ui/screens/system/power.py](../yoyopod/ui/screens/system/power.py)
- [yoyopod/ui/screens/system/lvgl/power_view.py](../yoyopod/ui/screens/system/lvgl/power_view.py)
- [yoyopod/app.py](../yoyopod/app.py)

Checklist:

- [ ] decide whether to expand `PowerScreen` into a broader `Setup` screen or keep voice settings on one of its pages
- [ ] add rows/actions for:
  - screen read on/off
  - output volume
  - mic muted/unmuted
  - voice commands enabled/disabled
- [ ] support both standard and one-button control paths
- [ ] keep display copy compact for the 240x280 Whisplay layout

Notes:

- current `PowerScreen` is already acting as the `Setup` screen
- this is the existing home for “device care” state, so it is the least disruptive first integration point

### 8. Add Screen Read Support

Files:

- [yoyopod/ui/screens/base.py](../yoyopod/ui/screens/base.py)
- selected concrete screen files such as:
  - [yoyopod/ui/screens/navigation/menu.py](../yoyopod/ui/screens/navigation/menu.py)
  - [yoyopod/ui/screens/navigation/hub.py](../yoyopod/ui/screens/navigation/hub.py)
  - [yoyopod/ui/screens/navigation/ask.py](../yoyopod/ui/screens/navigation/ask.py)
  - [yoyopod/ui/screens/system/power.py](../yoyopod/ui/screens/system/power.py)
  - [yoyopod/ui/screens/voip/contact_list.py](../yoyopod/ui/screens/voip/contact_list.py)
  - [yoyopod/ui/screens/voip/talk_contact.py](../yoyopod/ui/screens/voip/talk_contact.py)

Checklist:

- [ ] add a screen-summary hook to the base screen contract
- [ ] implement concise summaries for the key screens first
- [ ] add on-demand `read screen` command
- [ ] add auto-read on screen change when enabled
- [ ] avoid verbose full-screen dumps

Notes:

- screen read should be designed as a summary API, not as scraping rendered pixels

### 9. Add AI Requests Placeholder Path

Files:

- [yoyopod/ui/screens/navigation/ask.py](../yoyopod/ui/screens/navigation/ask.py)
- [yoyopod/voice/service.py](../yoyopod/voice/service.py)

Checklist:

- [ ] make `AI Requests` reachable from Ask
- [ ] reuse STT capture
- [ ] reply with a short spoken placeholder
- [ ] keep the handler boundary explicit so a future AI backend can slot in later

### 10. Dependency and Environment Work

Files:

- [pyproject.toml](../pyproject.toml)
- [docs/AUDIO_STACK.md](AUDIO_STACK.md)
- [README.md](../README.md)

Checklist:

- [ ] add Python dependency for Vosk if not already present
- [ ] document `espeak-ng` system dependency
- [ ] document Vosk small model install location
- [ ] document failure mode when model is missing
- [ ] document Pi setup steps for local voice features

### 11. Test Coverage

Files to add or update:

- [tests/config/test_models.py](../tests/config/test_models.py)
- [tests/ui/test_screen_routing.py](../tests/ui/test_screen_routing.py)
- [tests/core/test_audio_volume.py](../tests/core/test_audio_volume.py)
- suggested new tests:
  - `../tests/integrations/test_voice_commands.py`
  - `../tests/integrations/test_voice_service.py`
  - `../tests/ui/test_ask_screen.py`

Checklist:

- [ ] test config defaults and overrides
- [ ] test Ask submenu rendering/state transitions
- [ ] test transcript-to-command parsing
- [ ] test command execution dispatch
- [ ] test screen-summary output
- [ ] mock STT/TTS backends instead of requiring hardware

## Suggested Delivery Order

### Commit 1

- config models
- app context
- dependency/docs scaffolding

### Commit 2

- voice service layer
- deterministic command parser

### Commit 3

- Ask split into `Voice Commands` and `AI Requests`
- placeholder AI path

### Commit 4

- setup/settings integration
- volume and mic controls

### Commit 5

- screen read summaries
- auto-read behavior
- tests cleanup

## Immediate Next Coding Step

Start with the low-risk backbone:

- [yoyopod/config/models.py](../yoyopod/config/models.py)
- [yoyopod/core/app_context.py](../yoyopod/core/app_context.py)
- new `yoyopod/voice/` package skeleton

That gives the rest of the UI work a stable typed target.
