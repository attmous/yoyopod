# Canonical Config And Package Structure

**Last updated:** 2026-04-21
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
  - shared hardware truth: `input`, `display`, `communication_audio`, `media_audio`, `voice_audio`
- `config/power/backend.yaml`
  - PiSugar backend transport, watchdog, polling, and shutdown policy
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
- `config/boards/rpi-zero-2w/power/backend.yaml`
- `config/boards/rpi-zero-2w/network/cellular.yaml`
- `config/boards/radxa-cubie-a7z/audio/music.yaml`
- `config/boards/radxa-cubie-a7z/device/hardware.yaml`
- `config/boards/radxa-cubie-a7z/power/backend.yaml`

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
- `src/yoyopod/integrations/network/`
  - canonical network manager, modem models, and scaffold integration ownership
  - `__init__.py` is the app-facing seam
- `src/yoyopod/network/`
  - compatibility shims for the historical network import path
- `src/yoyopod/communication/`
  - `calling/`
  - low-level calling backends, messaging helpers, and compatibility shims
  - `messaging/`
  - `integrations/`
  - `__init__.py` is the app-facing seam
- `src/yoyopod/integrations/call/`
  - canonical call manager, messaging service, models, message store, call-history store, and voice-note services
  - `__init__.py` is the app-facing seam
- `src/yoyopod/backends/voip/`
  - canonical Liblinphone adapter, mock backend, protocol types, and native shim binding
- `src/yoyopod/integrations/contacts/`
  - mutable contacts/address-book concerns
  - owns the canonical contacts directory, models, and cloud-sync helpers
- `src/yoyopod/people/`
  - compatibility shims for the historical contacts import path
- `src/yoyopod/audio/`
  - local music/media behavior, history, output-volume coordination, and mpv backend wiring
  - `__init__.py` is the app-facing seam
- `src/yoyopod/integrations/power/`
  - canonical power manager, power models, and scaffold integration ownership
  - `__init__.py` is the app-facing seam
- `src/yoyopod/power/`
  - compatibility shims plus the remaining power-specific events and policies
- `src/yoyopod/integrations/voice/`
  - canonical voice manager, service alias, and typed voice models
  - `__init__.py` is the app-facing seam
- `src/yoyopod/backends/voice/`
  - concrete capture, playback, STT, and TTS adapters
- `src/yoyopod/voice/`
  - compatibility shims plus the remaining command grammar helpers
  - device inventory/helpers live outside this package
- `src/yoyopod/runtime/`, `src/yoyopod/coordinators/`, `src/yoyopod/app.py`
  - app/runtime composition

The app layer should import from domain seams such as:

- `yoyopod.integrations.network`
- `yoyopod.audio`
- `yoyopod.integrations.power`
- `yoyopod.integrations.call`
- `yoyopod.integrations.contacts`

It should not reach arbitrarily into domain internals unless the app is the
explicit owner of that internal boundary.

## Exemplar: Communication + People

The communication exemplar establishes:

- communication code under `src/yoyopod/communication/`
- public call-domain ownership under `src/yoyopod/integrations/call/`
- contacts under `src/yoyopod/integrations/contacts/`
- communication config separated from mutable people data
- runtime people data seeded into `data/people/contacts.yaml` from
  `config/people/contacts.seed.yaml` only when needed

Contacts are not communication config. The tracked people config file only says
where the mutable address book lives and which seed file can bootstrap it.

## Call Migration Pattern

The call migration follows the same cutover shape:

- communication policy remains under `config/communication/calling.yaml` and
  `config/communication/messaging.yaml`
- `src/yoyopod/integrations/call/` is the canonical owner of the public
  call manager, messaging service, models, message store, call-history, and voice-note seam
- `src/yoyopod/backends/voip/` is the canonical owner of the concrete
  Liblinphone and mock backend adapters plus protocol/binding types
- `src/yoyopod/communication/calling/`, `src/yoyopod/communication/messaging/`,
  and `src/yoyopod/communication/models.py` are retained as compatibility shims
- app/runtime composition depends on `yoyopod.integrations.call` instead of
  reaching through `yoyopod.communication.calling.*` for public call services

## Voice Migration Pattern

The voice migration adds the next reusable slice:

- voice policy under `config/voice/assistant.yaml`
- local voice capture and prompt selectors under `config/device/hardware.yaml`
  as `voice_audio.*`
- device listing and label helpers under `src/yoyopod/device/`
- `src/yoyopod/integrations/voice/` as the canonical owner of the public
  manager/models seam
- `src/yoyopod/voice/` retained for compatibility shims plus capture/STT/TTS
  helpers during the rewrite
- voice runtime and services consuming `ConfigManager.get_voice_settings()`
  and `yoyopod.integrations.voice` instead of reading app-shell config directly

## Network Migration Pattern

The network migration follows the same cutover shape:

- network policy under `config/network/cellular.yaml`
- `ConfigManager.get_network_settings()` as the typed runtime seam
- `src/yoyopod/integrations/network/` as the canonical owner of the public
  manager/models seam
- `src/yoyopod/network/` retained only as compatibility shims for historical
  imports
- app/runtime composition depending on `yoyopod.integrations.network.NetworkManager`
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

## Power Migration Pattern

The power migration follows the same cutover shape:

- power backend and shutdown policy under `config/power/backend.yaml`
- `ConfigManager.get_power_settings()` as the typed runtime seam
- `src/yoyopod/integrations/power/` as the canonical owner of the public
  manager/models seam
- `src/yoyopod/power/` retained as compatibility shims plus legacy events/policies
- app/runtime composition depending on `yoyopod.integrations.power.PowerManager`
  and `PowerManager.from_config_manager()`
  instead of reading power state from app-shell config
- power polling and PiSugar watchdog cadence owned by the power domain via
  `src/yoyopod/runtime/power_service.py`, while app/runtime composition still owns
  scheduling and shutdown orchestration

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
