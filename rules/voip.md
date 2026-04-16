# Communication (Liblinphone)

Applies to: `src/yoyopod/communication/**`, `src/yoyopod/people/**`

## Overview

The production VoIP path is Liblinphone-only:

- native Liblinphone shim under `src/yoyopod/communication/integrations/liblinphone_binding/`
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

Communication config is split by ownership:

- `config/communication/calling.yaml`
  - non-secret SIP identity, transport, STUN, calling policy
- `config/communication/messaging.yaml`
  - file transfer, message-store paths, voice-note policy
- `config/communication/calling.secrets.yaml`
  - SIP credentials only, gitignored
- `config/device/hardware.yaml`
  - shared communication audio device truth
- `config/people/directory.yaml`
  - paths for mutable people data only

Contacts are mutable user data under `data/people/contacts.yaml`, optionally
bootstrapped from `config/people/contacts.seed.yaml`.

## Audio

- Ring tone generation stays outside Liblinphone and may still use local helper tooling.
- Media devices should target the WM8960 codec on Whisplay-class hardware.
- Keep device selection configurable through `device/hardware.yaml` and env vars.
