# Communication (Liblinphone)

Applies to: `yoyopod/integrations/call/**`, `yoyopod/integrations/contacts/**`, `yoyopod/backends/voip/**`

## Overview

The production VoIP path is Rust-owned Liblinphone:

- Rust VoIP host under `device/voip/`
- Rust Liblinphone shim under `device/liblinphone-shim/`
- Python `RustHostBackend` only supervises the worker process and forwards commands
- `VoIPManager` only exposes command helpers and Rust runtime snapshots to the app

Do not reintroduce `linphonec` subprocess control or `.linphonerc`-driven runtime behavior.

## Integration Rules

- Liblinphone iteration is owned by the Rust VoIP host, not the Python app loop.
- Python must not expose live call-state or incoming-call callback ownership.
- Rust runtime snapshots are the contract into the Python app layer for:
  - registration state
  - call/session state
  - message summaries
  - voice-note state
  - lifecycle/recovery facts
- Native Liblinphone callbacks stay inside the Rust shim and are drained through Rust event queues.
- Voice-note recording is local-first:
  - record to WAV on-device
  - send through Liblinphone chat/file-transfer APIs
  - persist metadata through the Rust VoIP host message store

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
