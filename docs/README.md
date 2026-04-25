# YoYoPod Core Documentation Guide

This page is the entry point for the repo docs.

If you are new here, read these first:

1. [`README.md`](../README.md) for the repo overview and quick start
2. [`docs/DEVELOPMENT_GUIDE.md`](DEVELOPMENT_GUIDE.md) for setup, running, validation, and daily workflow
3. [`docs/SYSTEM_ARCHITECTURE.md`](SYSTEM_ARCHITECTURE.md) for the current runtime shape
4. [`docs/CANONICAL_STRUCTURE.md`](CANONICAL_STRUCTURE.md) for the current config/package ownership template

## Source of truth

When docs disagree, trust sources in this order:

1. Current code in `yoyopod/`
2. Current runtime and setup docs in this section
3. Rules and agent guidance in `rules/`, `AGENTS.md`, and `skills/`
4. Plans, checklists, and design specs
5. Archived docs under [`docs/archive/`](archive/)

Plan docs are useful, but they are not automatically the current implementation contract.

## Current runtime and setup docs

### Start here

- [`../README.md`](../README.md), repo overview and quick start
- [`CONTRIBUTOR_WORKFLOW.md`](CONTRIBUTOR_WORKFLOW.md), day-to-day contributor path and PR checklist
- [`DEVELOPMENT_GUIDE.md`](DEVELOPMENT_GUIDE.md), setup, running, validation, package layout
- [`RELEASE_PROCESS.md`](RELEASE_PROCESS.md), versioning, release artifacts, and GitHub release flow
- [`SYSTEM_ARCHITECTURE.md`](SYSTEM_ARCHITECTURE.md), current runtime architecture and startup/bootstrap flow
- [`CANONICAL_STRUCTURE.md`](CANONICAL_STRUCTURE.md), canonical config topology and package ownership template

### Setup, bringup, and deployment

- [`CONTRIBUTOR_WORKFLOW.md`](CONTRIBUTOR_WORKFLOW.md), contributor onboarding and daily workflow
- [`DEVELOPMENT_GUIDE.md`](DEVELOPMENT_GUIDE.md), main developer setup guide
- [`SETUP_CONTRACT.md`](SETUP_CONTRACT.md), repo-owned setup and dependency contract
- [`QUALITY_GATES.md`](QUALITY_GATES.md), current staged quality gate and audit contract
- [`RELEASE_PROCESS.md`](RELEASE_PROCESS.md), semantic versioning and release packaging flow
- [`DEV_PROD_LANES.md`](DEV_PROD_LANES.md), split dev/prod lane paths, services, and activation contract
- [`SLOT_DEPLOY.md`](SLOT_DEPLOY.md), fresh-board install, legacy-board migration, rollback, and OTA-ready release operations
- [`PI_PROFILING_WORKFLOW.md`](PI_PROFILING_WORKFLOW.md), bounded profiling and Pi investigation workflow
- [`DEPLOYED_PI_DEPENDENCIES.md`](DEPLOYED_PI_DEPENDENCIES.md), deployed/runtime dependency inventory
- [`PI_DEV_WORKFLOW.md`](PI_DEV_WORKFLOW.md), day-to-day Raspberry Pi workflow
- [`RPI_SMOKE_VALIDATION.md`](RPI_SMOKE_VALIDATION.md), validation checklist for CI-safe and on-device checks
- [`CUBIE_A7Z_BRINGUP.md`](CUBIE_A7Z_BRINGUP.md), Cubie board bringup notes

### Core runtime architecture

- [`SYSTEM_ARCHITECTURE.md`](SYSTEM_ARCHITECTURE.md), top-level runtime topology plus startup/bootstrap flow
- [`CROSS_SCREEN_OVERLAYS.md`](CROSS_SCREEN_OVERLAYS.md), first-class contract for cross-screen overlay ownership and ordering
- [`CANONICAL_STRUCTURE.md`](CANONICAL_STRUCTURE.md), canonical config topology and domain package ownership
- [`CLOUD_PROVISIONING_AND_BACKEND.md`](CLOUD_PROVISIONING_AND_BACKEND.md), claimed-device auth, config sync, cache/status files, MQTT telemetry, and current backend-integration status
- [`RUNTIME_EVENT_FLOW.md`](RUNTIME_EVENT_FLOW.md), current event pipeline and coordinator ownership
- [`VOICE_STT_MODEL_LIFECYCLE.md`](VOICE_STT_MODEL_LIFECYCLE.md), offline Vosk retention policy and measured footprint
- [`DISPLAY_HAL_ARCHITECTURE.md`](DISPLAY_HAL_ARCHITECTURE.md), display abstraction and adapters
- [`INPUT_HAL_ARCHITECTURE.md`](INPUT_HAL_ARCHITECTURE.md), semantic input model and adapters
- [`POWER_MODULE.md`](POWER_MODULE.md), power, battery, RTC, watchdog
- [`AUDIO_STACK.md`](AUDIO_STACK.md), deployed ALSA routing, WM8960 headroom, and mpv output behavior
- [`REMOTE_PLAYBACK.md`](REMOTE_PLAYBACK.md), backend-issued playback, cache, and device-local media import contract
- [`LOCAL_FIRST_MUSIC_PLAN.md`](LOCAL_FIRST_MUSIC_PLAN.md), current music direction and constraints
- [`MPV_DEPENDENCIES.md`](MPV_DEPENDENCIES.md), mpv-specific dependency and integration notes

## Plans, specs, and design work

These files are useful for context, but they are not all the same kind of document.

### Transitional or partly historical design docs

- [`LVGL_MIGRATION_PLAN.md`](LVGL_MIGRATION_PLAN.md), historical migration record with some still-relevant rationale
- [`VOICE_COMMAND_PLAN.md`](VOICE_COMMAND_PLAN.md), transitional design record, not the current `Ask` implementation contract
- [`VOICE_COMMAND_CHECKLIST.md`](VOICE_COMMAND_CHECKLIST.md), historical implementation checklist from an older branch snapshot
- [`ASK_SCREEN_DESIGN_SPEC.md`](ASK_SCREEN_DESIGN_SPEC.md), design target for the unified `Ask` screen, not automatic proof of implementation

### Active design or contract docs

- [`GLOBAL_AUDIO_DEVICE_FACADE_CONTRACT.md`](GLOBAL_AUDIO_DEVICE_FACADE_CONTRACT.md)
- [`WHISPLAY_SIMULATION_PARITY_CONTRACT.md`](WHISPLAY_SIMULATION_PARITY_CONTRACT.md)
- [`design-previews/`](design-previews/)

If one of these conflicts with the current code or the current runtime docs above, trust the current code and the current runtime docs.

## Historical implementation records

These are useful when you need to understand how the repo got here, but they are not the top-level source of truth for current architecture. Each of these files should say that plainly at the top.

- [`INTEGRATION_PLAN.md`](INTEGRATION_PLAN.md), implemented milestone record for VoIP + local music integration
- [`UI_RESTRUCTURE_PROPOSAL.md`](UI_RESTRUCTURE_PROPOSAL.md), refactor status record for the UI split and remaining cleanup
- [`PHASE2_SUMMARY.md`](PHASE2_SUMMARY.md), milestone summary for early screen integration
- [`CUBIE_A7Z_PIMORONI_SETUP.md`](CUBIE_A7Z_PIMORONI_SETUP.md), historical non-Whisplay bringup notes

## Generated planning workspace

- [`superpowers/README.md`](superpowers/README.md), status and usage notes for generated plan/spec workspaces
- [`superpowers/`](superpowers/), historical agent-generated plans and specs that may retain older repo names or environment-specific paths

Treat this directory as preserved planning context, not as the current implementation contract.

## Archived history

- [`archive/README.md`](archive/README.md), archive policy
- [`archive/`](archive/), historical milestone notes and prior proposals

Archive files are for historical context only. They are not the source of truth for the current runtime.

## Contributor and agent guidance

- [`../AGENTS.md`](../AGENTS.md), current agent/repo guidance
- [`../rules/project.md`](../rules/project.md), project rules and common commands
- [`../rules/architecture.md`](../rules/architecture.md), architecture constraints
- [`../rules/code-style.md`](../rules/code-style.md), style and typing rules
- [`../rules/deploy.md`](../rules/deploy.md), deploy workflow
- [`../skills/`](../skills/), task-specific Pi workflow skills

## Suggested reading paths

### New developer

1. `README.md`
2. `docs/README.md`
3. `docs/CONTRIBUTOR_WORKFLOW.md`
4. `docs/DEVELOPMENT_GUIDE.md`
5. `docs/SYSTEM_ARCHITECTURE.md`
6. `rules/project.md`

### Working on runtime code

1. `docs/SYSTEM_ARCHITECTURE.md`
2. `docs/CLOUD_PROVISIONING_AND_BACKEND.md` when the work touches backend auth, provisioning, config, or telemetry
3. subsystem doc for the area you are changing
4. `AGENTS.md`
5. relevant files under `yoyopod/`

### Working on Raspberry Pi deployment

1. `docs/CONTRIBUTOR_WORKFLOW.md`
2. `docs/SETUP_CONTRACT.md`
3. `docs/DEVELOPMENT_GUIDE.md`
4. `docs/DEV_PROD_LANES.md`
5. `docs/SLOT_DEPLOY.md`
6. `docs/PI_DEV_WORKFLOW.md`
7. `docs/RPI_SMOKE_VALIDATION.md`
