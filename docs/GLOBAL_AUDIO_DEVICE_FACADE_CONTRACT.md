# YoyoPod Global Audio Device Facade Contract

**Last Updated:** 2026-04-10
**Status:** Proposed

## Problem Statement

YoyoPod currently reaches ALSA and device selection through multiple partially overlapping paths:

- music playback uses `media_audio.alsa_device` plus `OutputVolumeController`
- Liblinphone receives its own playback, ringer, capture, and media device IDs
- `LiblinphoneBackend` also applies capture-side `amixer` commands directly
- voice-command capture resolves `arecord` devices independently
- spoken prompts use `AlsaOutputPlayer`, which resolves `aplay` devices independently

That means the app does not yet have one global audio hardware contract. Device resolution, mixer writes, and defaults are split across multiple feature boundaries, which makes the Pi harder to reason about and easier to misconfigure.

## Goals

- establish one app-owned source of truth for input and output audio routing
- centralize ALSA mixer commands behind one facade
- keep music playback, calls, voice commands, and spoken prompts aligned to the same resolved hardware profile unless explicitly overridden
- preserve config and environment override flexibility
- make effective device selection inspectable in logs, tests, and Pi status workflows

## Non-Goals

- replace `mpv`, Liblinphone, `arecord`, or `aplay`
- redesign call interruption or playback policy
- add a full user-facing audio routing UI in this phase
- solve advanced hot-plug or multi-device profiles beyond the current Pi target

## Current State

### Music

- `src/yoyopod/audio/music/process.py` launches `mpv` with one ALSA target
- `src/yoyopod/audio/volume.py` owns app-facing output volume and writes selected ALSA output controls

### Calls

- `config/device/hardware.yaml` carries shared communication audio device IDs
- `src/yoyopod/communication/calling/backend.py` directly issues startup `amixer` capture-tuning commands

### Voice Commands

- `src/yoyopod/voice/capture.py` resolves `arecord` capture candidates
- `src/yoyopod/voice/output.py` resolves `aplay` playback candidates
- `src/yoyopod/voice/tts.py` depends on that playback helper for spoken prompts

The effect is that one physical audio stack is managed by several different policy owners.

## Contract

### 1. The application owns one resolved audio hardware profile

At startup, YoyoPod must resolve one effective audio hardware profile for the app run.

That profile should include:

- playback output device
- ringer output device
- capture input device
- media device
- voice-prompt output device
- voice-command capture device
- output mixer controls
- capture mixer controls and startup tuning

Feature modules should consume that resolved profile. They should not each invent their own ALSA policy.

### 2. All ALSA policy moves behind one facade

Raw `amixer`, `aplay -L`, `arecord -L`, and ALSA-name normalization policy should live in one app-owned audio layer.

Backends may still execute their own domain-specific runtime commands, but they should not decide system-wide audio defaults independently.

### 3. Shared defaults come first, explicit overrides remain allowed

The facade should resolve shared defaults first and then layer explicit overrides on top.

That means:

- one default output route for music and short spoken prompts
- one default capture route for voice commands and calls
- optional explicit per-role overrides when the product truly needs them

Per-role divergence should be configuration, not accidental drift.

### 4. The resolved profile must be consumable by every backend shape

The facade must be able to produce backend-specific selectors for:

- `mpv`
- Liblinphone
- `arecord`
- `aplay`
- future ALSA-backed helpers

That includes mapping friendly config values like `ALSA: wm8960-soundcard` into the concrete form each subprocess expects.

### 5. Mixer state is application state

Output volume, mic capture tuning, and mute-related mixer state must be treated as app-level state with one owner.

No backend should silently re-apply conflicting mixer gain after startup.

## Proposed Architecture

### New Facade

Add one app-facing facade, for example:

- `AudioDeviceFacade`

Suggested home:

- `src/yoyopod/audio/devices.py`
- or `src/yoyopod/audio/hardware.py`

Primary responsibilities:

- inspect ALSA hardware and available routes
- resolve config plus env overrides into one effective profile
- normalize ALSA identifiers across `mpv`, Liblinphone, `aplay`, and `arecord`
- apply startup mixer policy
- expose read and write operations for output volume and capture tuning
- provide helper methods for feature backends to consume resolved routes

### Suggested Supporting Models

- `ResolvedAudioDevices`
- `AudioMixerProfile`
- `AudioRouteOverrides`
- `AudioHardwareInventory`

These should be typed models, not loose dicts.

### Suggested App Integration

`YoyoPodApp` should build the facade once and hand resolved audio information to the feature layers:

- `MpvBackend`
  - receives resolved playback device
- `OutputVolumeController`
  - becomes an implementation detail under the facade or is owned by it
- `LiblinphoneBackend`
  - receives resolved playback, ringer, capture, and media IDs
  - no longer owns startup `amixer` policy
- `SubprocessAudioCaptureBackend`
  - receives resolved `arecord` capture device
- `AlsaOutputPlayer`
  - receives resolved `aplay` output device
- `EspeakNgTextToSpeechBackend`
  - speaks through the same resolved prompt output route

## Configuration Contract

Audio routing should become shared configuration first and backend-specific configuration second.

Suggested direction:

- keep backend-specific codec and SIP behavior in `config/communication/calling.yaml`
- move shared device routing and mixer policy under the main app audio config
- let env overrides feed the shared resolver, not separate feature paths

Illustrative shape:

```yaml
audio:
  output_device: default
  capture_device: "ALSA: wm8960-soundcard"
  ringer_device: inherit
  media_device: inherit
  prompt_output_device: inherit
  mixer:
    output_controls: ["Speaker", "Headphone", "Playback"]
    capture_control: "Capture"
    adc_pcm_value: 195
    enable_input_boost: true
    mic_gain: 80
```

The exact key names can change, but the contract is that device and mixer policy become globally owned by the app.

## Verification Contract

This architecture must be testable without real ALSA hardware.

Required coverage:

- unit tests for route resolution and override precedence
- unit tests for ALSA command generation
- integration tests showing the app wires one resolved profile into music, calls, and voice services
- Pi validation that the same effective routes are used after restart

Logs and status commands should show the resolved audio profile so field debugging does not require guessing which layer won.

## Acceptance Criteria

- one app-owned facade resolves audio devices and mixer policy for the whole app run
- no feature layer outside the shared audio subsystem issues ad hoc startup ALSA policy commands
- music playback, calls, voice commands, and spoken prompts use the same intended WM8960 routes by default on the Pi
- output volume and mic capture tuning remain stable across restarts
- config and env overrides still work, but now flow through one resolver

## Rollout Outline

1. inventory every current ALSA and device-selection call site
2. introduce typed resolved-audio models and the new facade
3. move mixer command generation out of feature modules
4. wire `mpv`, Liblinphone, STT capture, and TTS playback through the shared facade
5. add tests and Pi status reporting for the resolved profile
