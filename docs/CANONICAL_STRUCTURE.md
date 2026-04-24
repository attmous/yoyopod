# Canonical Config And Package Structure

**Last updated:** 2026-04-22
**Status:** Current implementation reference

This document defines the reusable structure pattern established by the
call + contacts hard cut and the frozen Phase A package layout.

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

YoYoPod uses a hybrid ownership model:

- domain packages own domain behavior and models
- app/runtime composition owns app wiring and lifecycle
- shared infrastructure keeps explicit shared homes

Frozen canonical package homes:

- `yoyopod/app.py`
  - thin compatibility re-export of `YoyoPodApp` (imports from `yoyopod.core.application`)
- `yoyopod/main.py`
  - process entrypoint and bootstrap plumbing
- `yoyopod/config/`
  - typed config loading, composition, and validation
- `yoyopod/core/`
  - framework and cross-cutting primitives
  - `application.py`: canonical scaffold app object
  - `bus.py`, `states.py`, `services.py`, `scheduler.py`: shared Home Assistant-style spine
  - `logging.py`: centralized loguru configuration and runtime logging helpers
  - `events.py`: universal `StateChangedEvent` plus cross-cutting app events only
  - `focus.py`, `recovery.py`, `status.py`: cross-domain mechanics and runtime status
  - `diagnostics/`: event log, snapshots, watchdog helpers
  - `hardware.py`: only shared hardware metadata/helpers that do not belong to one domain
- `yoyopod/integrations/call/`
  - canonical call-domain seam: calls, registration, messaging, history, and voice notes
  - owns call-domain typed events in `events.py`
  - `runtime.py` owns call-flow orchestration and screen transitions
- `yoyopod/integrations/music/`
  - canonical music-domain seam
  - owns music-domain typed events in `events.py`
  - `runtime.py` owns playback-flow orchestration and visible now-playing refreshes
- `yoyopod/integrations/power/`
  - canonical power-domain seam
  - owns power-domain typed events in `events.py` and battery safety policy in `policies.py`
  - `service.py` owns live power polling, watchdog cadence, power snapshot application, and safety-event emission
- `yoyopod/integrations/network/`
  - canonical cellular/network seam
  - owns modem / PPP / signal events in `events.py`
- `yoyopod/integrations/location/`
  - canonical GPS/location seam split from network
  - owns GPS fix/no-fix events in `events.py`
- `yoyopod/integrations/cloud/`
  - canonical cloud-sync and telemetry seam
- `yoyopod/integrations/contacts/`
  - canonical contacts/address-book seam
- `yoyopod/integrations/voice/`
  - canonical voice/STT/TTS seam
- `yoyopod/integrations/display/`
  - canonical display awake/sleep/brightness/timeout seam
- `yoyopod/backends/`
  - concrete adapters only: `voip/`, `music/`, `power/`, `network/`, `location/`, `voice/`
- `yoyopod/ui/`
  - display adapters, input adapters, and screens
  - `ui/input/` owns input adapters including GPIO compatibility helpers

Temporary migration buckets are not part of the canonical target:

- thin root compatibility wrappers such as `events.py` and `fsm.py`

The app layer should import from domain seams such as:

- `yoyopod.integrations.network`
- `yoyopod.integrations.music`
- `yoyopod.integrations.power`
- `yoyopod.integrations.call`
- `yoyopod.integrations.contacts`

It should not reach arbitrarily into domain internals unless the app is the
explicit owner of that internal boundary.

Core package exports should follow the same rule:

- `yoyopod.core.events` owns only cross-cutting event types such as
  `StateChangedEvent`, lifecycle, focus, backend-stop, and display activity events
- domain events must be imported from their owning packages such as
  `yoyopod.integrations.call.events`,
  `yoyopod.integrations.music.events`,
  `yoyopod.integrations.network.events`, and
  `yoyopod.integrations.location.events`
- `yoyopod.core.__init__` should not re-export integration-owned event types

## Canonical Test Layout

The test tree should mirror the same ownership split as `yoyopod/`.

- `tests/core/`
  - core primitives and cross-cutting runtime helpers
- `tests/integrations/`
  - domain-level tests for `integrations/`
- `tests/backends/`
  - adapter-level tests for `backends/`
- `tests/config/`
  - typed config loading, composition, and validation
- `tests/cli/`
  - `yoyopod_cli/` command and helper coverage
- `tests/ui/`
  - display, input, screen, and LVGL coverage for `ui/`
- `tests/e2e/`
  - cross-domain orchestration and soak-style behavior checks
- `tests/fixtures/`
  - shared fakes, builders, and reusable test helpers

Only truly repo-global tests should remain flat under `tests/`. Package-owned
tests should keep moving into these buckets as their ownership becomes clearer.

## Exemplar: Call + Contacts

The call + contacts cut establishes:

- public call-domain ownership under `yoyopod/integrations/call/`
- contacts under `yoyopod/integrations/contacts/`
- communication config separated from mutable people data
- runtime people data seeded into `data/people/contacts.yaml` from
  `config/people/contacts.seed.yaml` only when needed
- the historical facade packages (`communication/`, `people/`) removed from `yoyopod/`

Contacts are not communication config. The tracked people config file only says
where the mutable address book lives and which seed file can bootstrap it.

## Call Migration Pattern

The call migration follows the same cutover shape:

- communication policy remains under `config/communication/calling.yaml` and
  `config/communication/messaging.yaml`
- `yoyopod/integrations/call/` is the canonical owner of the public
  call manager, session FSM/policy, lifecycle tracker, messaging service, models, message store,
  call-history, and voice-note seam
- `yoyopod/backends/voip/` is the canonical owner of the concrete
  Liblinphone and mock backend adapters plus protocol/binding types
- app/runtime composition depends on `yoyopod.integrations.call` instead of historical
  communication-package import paths

## Voice Migration Pattern

The voice migration adds the next reusable slice:

- voice policy under `config/voice/assistant.yaml`
- local voice capture and prompt selectors under `config/device/hardware.yaml`
  as `voice_audio.*`
- shared audio-device listing and label helpers under `yoyopod/core/hardware.py`
- `yoyopod/integrations/voice/` as the canonical owner of the public
  manager/models seam
- `yoyopod/backends/voice/` as the canonical owner of the concrete capture,
  playback, STT, and TTS adapters
- voice runtime and services consuming `ConfigManager.get_voice_settings()`
  and `yoyopod.integrations.voice` instead of reading app-shell config directly

## Network Migration Pattern

The network migration follows the same cutover shape:

- network policy under `config/network/cellular.yaml`
- `ConfigManager.get_network_settings()` as the typed runtime seam
- `yoyopod/integrations/network/` as the canonical owner of the public
  manager/models seam
- app/runtime composition depending on `yoyopod.integrations.network.NetworkManager`
  instead of reading network state from app-shell config

## Media Migration Pattern

The media/audio migration follows the same cutover shape:

- media policy under `config/audio/music.yaml`
- device-owned playback routing under `config/device/hardware.yaml` as `media_audio.*`
- mutable recent-track history under `data/media/`
- `ConfigManager.get_media_settings()` as the typed runtime seam for `music` policy
  plus device-owned `audio` routing
- `yoyopod/integrations/music/` as the domain-owned public seam
- `yoyopod/backends/music/` as the adapter-owned implementation seam
- app/runtime composition depending on the `yoyopod.integrations.music` seam via
  `MusicConfig.from_config_manager()` instead of hand-mapping media fields

## Power Migration Pattern

The power migration follows the same cutover shape:

- power backend and shutdown policy under `config/power/backend.yaml`
- `ConfigManager.get_power_settings()` as the typed runtime seam
- `yoyopod/integrations/power/` as the canonical owner of the public
  manager/models/events/policies seam
- app/runtime composition depending on `yoyopod.integrations.power.PowerManager`
  and `PowerManager.from_config_manager()`
  instead of reading power state from app-shell config
- power polling and PiSugar watchdog cadence owned by the power domain via
  `yoyopod/integrations/power/service.py`

## Template For Future Migrations

When migrating another domain:

1. choose one public domain seam under `yoyopod/integrations/<domain>/`
2. split tracked config into domain-owned files under `config/<domain>/`
3. keep shared hardware truth in `config/device/hardware.yaml` unless the new
   setting is truly domain-owned policy
4. define an app-facing seam in `yoyopod/integrations/<domain>/__init__.py`
5. route mutable user data into `data/`, not tracked config
6. mirror the same relative file structure in `config/boards/<board>/`
7. add focused tests for composition, boundaries, and bootstrap behavior
