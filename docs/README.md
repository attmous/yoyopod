# YoyoPod Core Documentation Guide

This page is the entry point for the repo docs.

If you are new here, read these first:

1. [`README.md`](../README.md) for the repo overview and quick start
2. [`docs/DEVELOPMENT_GUIDE.md`](DEVELOPMENT_GUIDE.md) for setup, running, validation, and daily workflow
3. [`docs/SYSTEM_ARCHITECTURE.md`](SYSTEM_ARCHITECTURE.md) for the current runtime shape

## Source of truth

When docs disagree, trust sources in this order:

1. Current code in `yoyopy/`
2. Current runtime and setup docs in this section
3. Rules and agent guidance in `rules/`, `AGENTS.md`, and `skills/`
4. Plans, checklists, and design specs
5. Archived docs under [`docs/archive/`](archive/)

Plan docs are useful, but they are not automatically the current implementation contract.

## Current runtime and setup docs

### Start here

- [`../README.md`](../README.md), repo overview and quick start
- [`DEVELOPMENT_GUIDE.md`](DEVELOPMENT_GUIDE.md), setup, running, validation, package layout
- [`SYSTEM_ARCHITECTURE.md`](SYSTEM_ARCHITECTURE.md), current runtime architecture

### Setup, bringup, and deployment

- [`DEVELOPMENT_GUIDE.md`](DEVELOPMENT_GUIDE.md), main developer setup guide
- [`DEPLOYED_PI_DEPENDENCIES.md`](DEPLOYED_PI_DEPENDENCIES.md), deployed/runtime dependency inventory
- [`PI_DEV_WORKFLOW.md`](PI_DEV_WORKFLOW.md), day-to-day Raspberry Pi workflow
- [`RPI_SMOKE_VALIDATION.md`](RPI_SMOKE_VALIDATION.md), validation checklist for CI-safe and on-device checks
- [`CUBIE_A7Z_BRINGUP.md`](CUBIE_A7Z_BRINGUP.md), Cubie board bringup notes
- [`CUBIE_A7Z_PIMORONI_SETUP.md`](CUBIE_A7Z_PIMORONI_SETUP.md), Cubie + Pimoroni setup notes

### Core runtime architecture

- [`SYSTEM_ARCHITECTURE.md`](SYSTEM_ARCHITECTURE.md), top-level runtime topology
- [`DISPLAY_HAL_ARCHITECTURE.md`](DISPLAY_HAL_ARCHITECTURE.md), display abstraction and adapters
- [`INPUT_HAL_ARCHITECTURE.md`](INPUT_HAL_ARCHITECTURE.md), semantic input model and adapters
- [`POWER_MODULE.md`](POWER_MODULE.md), power, battery, RTC, watchdog
- [`AUDIO_STACK.md`](AUDIO_STACK.md), local playback and output-volume behavior
- [`LOCAL_FIRST_MUSIC_PLAN.md`](LOCAL_FIRST_MUSIC_PLAN.md), current music direction and constraints
- [`MPV_DEPENDENCIES.md`](MPV_DEPENDENCIES.md), mpv-specific dependency and integration notes

## Plans, specs, and design work

These files are useful for context, but they may describe work in progress, transitional architecture, or older intended behavior.

- [`LVGL_MIGRATION_PLAN.md`](LVGL_MIGRATION_PLAN.md)
- [`VOICE_COMMAND_PLAN.md`](VOICE_COMMAND_PLAN.md)
- [`VOICE_COMMAND_CHECKLIST.md`](VOICE_COMMAND_CHECKLIST.md)
- [`ASK_SCREEN_DESIGN_SPEC.md`](ASK_SCREEN_DESIGN_SPEC.md)
- [`GLOBAL_AUDIO_DEVICE_FACADE_CONTRACT.md`](GLOBAL_AUDIO_DEVICE_FACADE_CONTRACT.md)
- [`WHISPLAY_SIMULATION_PARITY_CONTRACT.md`](WHISPLAY_SIMULATION_PARITY_CONTRACT.md)
- [`design-previews/`](design-previews/)

If one of these conflicts with the current code or the current runtime docs above, treat it as design history unless it is explicitly updated.

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
3. `docs/DEVELOPMENT_GUIDE.md`
4. `docs/SYSTEM_ARCHITECTURE.md`
5. `rules/project.md`

### Working on runtime code

1. `docs/SYSTEM_ARCHITECTURE.md`
2. subsystem doc for the area you are changing
3. `AGENTS.md`
4. relevant files under `yoyopy/`

### Working on Raspberry Pi deployment

1. `docs/DEVELOPMENT_GUIDE.md`
2. `docs/PI_DEV_WORKFLOW.md`
3. `docs/RPI_SMOKE_VALIDATION.md`
4. `skills/yoyopod-*.md` guidance via `AGENTS.md`
