# Canonical Config And Package Structure

**Last updated:** 2026-04-16
**Status:** Current migration reference

This document defines the reusable structure pattern established by the
communication + people exemplar migration.

## Goals

- split authored config by clear ownership
- compose authored config into one typed runtime model
- keep mutable user data out of tracked config
- make secret boundaries explicit and validated
- give each domain a clear package home with a small app-facing seam

## Canonical Config Topology

Tracked authored config lives under `config/` and is split by ownership:

- `config/app/core.yaml`
  - app shell concerns: `app`, `ui`, `logging`, `diagnostics`
- `config/audio/music.yaml`
  - local music policy, startup volume, and media runtime paths
- `config/device/hardware.yaml`
  - shared hardware truth: `input`, `display`, `power`, `communication_audio`, `media_audio`, `voice_audio`
- `config/network/cellular.yaml`
  - cellular modem policy and transport settings
- `config/voice/assistant.yaml`
  - local voice policy and assistant defaults
- `config/communication/calling.yaml`
  - non-secret SIP identity, calling policy, call-history path
- `config/communication/messaging.yaml`
  - messaging policy, message-store paths, voice-note policy
- `config/communication/integrations/liblinphone_factory.conf`
  - repo-owned Liblinphone integration defaults
- `config/people/directory.yaml`
  - paths only for mutable people data and bootstrap seed files
- `config/people/contacts.seed.yaml`
  - tracked bootstrap/import-export seed data only

Untracked local secrets live in:

- `config/communication/calling.secrets.yaml`

Mutable runtime user data lives outside tracked config:

- `data/communication/`
- `data/media/`
- `data/people/`

### Composition Rule

Runtime code should consume one composed typed model, not read domain YAML files
ad hoc.

- `ConfigManager` composes the canonical files
- `YoyoPodRuntimeConfig` is the single typed runtime model
- `load_composed_app_settings()` is the app-shell loader for `app` + `device`

### Secret Boundary Rule

Tracked authored config must not contain SIP credentials.

- `communication/calling.yaml`, `communication/messaging.yaml`, and `device/hardware.yaml`
  are validated to reject `sip_password`, `sip_password_ha1`, or a tracked `secrets:` block
- credentials belong in `communication/calling.secrets.yaml` or env vars

### Board Overlay Rule

Board overlays mirror the same relative path under `config/boards/<board>/`.

Examples:

- `config/boards/rpi-zero-2w/audio/music.yaml`
- `config/boards/rpi-zero-2w/device/hardware.yaml`
- `config/boards/rpi-zero-2w/network/cellular.yaml`
- `config/boards/radxa-cubie-a7z/audio/music.yaml`
- `config/boards/radxa-cubie-a7z/device/hardware.yaml`

Future domains should follow the same pattern instead of inventing one-off
overlay shapes.

## Canonical Package Ownership

YoyoPod uses a hybrid ownership model:

- domain packages own domain behavior and models
- app/runtime composition owns app wiring and lifecycle
- shared infrastructure keeps explicit shared homes

Current exemplar package homes:

- `src/yoyopod/device/`
  - device-owned helpers shared across domains
- `src/yoyopod/network/`
  - cellular modem lifecycle, transport, PPP, and GPS behavior
  - `__init__.py` is the app-facing seam
- `src/yoyopod/communication/`
  - `calling/`
  - `messaging/`
  - `integrations/`
  - `__init__.py` is the app-facing seam
- `src/yoyopod/people/`
  - mutable contacts/address-book concerns
  - `__init__.py` is the app-facing seam
- `src/yoyopod/audio/`
  - local music/media behavior, history, output-volume coordination, and mpv backend wiring
  - `__init__.py` is the app-facing seam
- `src/yoyopod/voice/`
  - local voice behavior, models, and backends
  - device inventory/helpers live outside this package
- `src/yoyopod/runtime/`, `src/yoyopod/coordinators/`, `src/yoyopod/app.py`
  - app/runtime composition

The app layer should import from domain seams such as:

- `yoyopod.network`
- `yoyopod.audio`
- `yoyopod.communication`
- `yoyopod.people`

It should not reach arbitrarily into domain internals unless the app is the
explicit owner of that internal boundary.

## Exemplar: Communication + People

The communication exemplar establishes:

- communication code under `src/yoyopod/communication/`
- contacts under `src/yoyopod/people/`
- communication config separated from mutable people data
- runtime people data seeded into `data/people/contacts.yaml` from
  `config/people/contacts.seed.yaml` only when needed

Contacts are not communication config. The tracked people config file only says
where the mutable address book lives and which seed file can bootstrap it.

## Voice Migration Pattern

The voice migration adds the next reusable slice:

- voice policy under `config/voice/assistant.yaml`
- local voice capture and prompt selectors under `config/device/hardware.yaml`
  as `voice_audio.*`
- device listing and label helpers under `src/yoyopod/device/`
- voice runtime and services consuming `ConfigManager.get_voice_settings()`
  instead of reading app-shell config directly

## Network Migration Pattern

The network migration follows the same cutover shape:

- network policy under `config/network/cellular.yaml`
- `ConfigManager.get_network_settings()` as the typed runtime seam
- `src/yoyopod/network/` as the domain-owned package home
- app/runtime composition depending on `NetworkManager.from_config_manager()`
  instead of reading network state from app-shell config

## Media Migration Pattern

The media/audio migration follows the same cutover shape:

- media policy under `config/audio/music.yaml`
- device-owned playback routing under `config/device/hardware.yaml` as `media_audio.*`
- mutable recent-track history under `data/media/`
- `ConfigManager.get_media_settings()` as the typed runtime seam for `music` policy
  plus device-owned `audio` routing
- `src/yoyopod/audio/` as the domain-owned package home
- app/runtime composition depending on the `yoyopod.audio` seam via
  `MusicConfig.from_config_manager()` instead of hand-mapping media fields

## Template For Future Migrations

When migrating another domain:

1. choose one domain package home under `src/yoyopod/<domain>/`
2. split tracked config into domain-owned files under `config/<domain>/`
3. keep shared hardware truth in `config/device/hardware.yaml` unless the new
   setting is truly domain-owned policy
4. define an app-facing seam in `src/yoyopod/<domain>/__init__.py`
5. route mutable user data into `data/`, not tracked config
6. mirror the same relative file structure in `config/boards/<board>/`
7. add focused tests for composition, boundaries, and bootstrap behavior
