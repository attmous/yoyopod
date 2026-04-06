# VoIP (Liblinphone)

Applies to: `yoyopy/voip/**`

## Overview

The production VoIP path is Liblinphone-only:

- native Liblinphone shim under `yoyopy/voip/liblinphone_binding/`
- CPython `cffi` binding against the shim header only
- `VoIPManager` as the app-facing facade for registration, calls, text messages, and voice notes

Do not reintroduce `linphonec` subprocess control or `.linphonerc`-driven runtime behavior.

## Integration Rules

- Liblinphone is driven from the app loop through `VoIPBackend.iterate()`.
- Native Liblinphone callbacks must never call Python directly from arbitrary threads.
- Typed backend events are the contract into the app layer:
  - registration
  - call state
  - incoming call
  - message received
  - message delivery change
  - message download complete
  - message failure
- Voice-note recording is local-first:
  - record to WAV on-device
  - send through Liblinphone chat/file-transfer APIs
  - persist metadata through `VoIPMessageStore`

## Configuration

SIP and messaging config lives in `config/voip_config.yaml`:

- SIP account, transport, STUN server
- HA1 hash authentication
- Liblinphone factory config path
- file-transfer server URL
- message store directory
- voice-note store directory
- voice-note max duration

Trusted peer identities live in `config/contacts.yaml`.

## Audio

- Ring tone generation stays outside Liblinphone and may still use local helper tooling.
- Media devices should target the WM8960 codec on Whisplay-class hardware.
- Keep device selection configurable through the existing env/config path.
