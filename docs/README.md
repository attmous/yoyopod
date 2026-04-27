# YoYoPod Core Documentation Guide

This page is the entry point for repo documentation.

If you are new here, read these first:

1. [`../README.md`](../README.md) for the repo overview and quick start
2. [`operations/DEVELOPMENT_GUIDE.md`](operations/DEVELOPMENT_GUIDE.md) for setup, running, validation, and daily workflow
3. [`architecture/SYSTEM_ARCHITECTURE.md`](architecture/SYSTEM_ARCHITECTURE.md) for the current runtime shape
4. [`architecture/CANONICAL_STRUCTURE.md`](architecture/CANONICAL_STRUCTURE.md) for config and package ownership

## Source Of Truth

When docs disagree, trust sources in this order:

1. Current code in `yoyopod/`
2. Current runtime, operations, hardware, feature, and design docs under the folders below
3. Rules and agent guidance in `rules/`, `AGENTS.md`, and `skills/`
4. Generated plans, checklists, and design specs
5. Archived docs under [`archive/`](archive/)

Plan docs are useful context, but they are not automatically the current implementation contract.

## Folder Map

- [`architecture/`](architecture/README.md) - current runtime topology, package/config ownership, event flow, display/input contracts, and cross-screen UI contracts.
- [`operations/`](operations/README.md) - contributor workflow, setup, quality gates, release flow, dev/prod lanes, Pi validation, profiling, and OTA/deploy operations.
- [`hardware/`](hardware/README.md) - audio, power, deployed Pi dependencies, and board bringup notes.
- [`features/`](features/README.md) - cloud provisioning, cloud voice, offline voice model lifecycle, local music, mpv, and remote playback contracts.
- [`design/`](design/README.md) - active screen/UI design targets, parity contracts, and visual previews.
- [`history/`](history/README.md) - transitional plans and milestone records that are useful context but not source of truth.
- [`product/`](product/README.md) - product definition, V1 scope, positioning, technical priorities, and research material.
- [`superpowers/`](superpowers/README.md) - preserved agent-generated specs and plans.
- [`archive/`](archive/README.md) - retired historical material.
- [`assets/`](assets/) - images and media used by docs.

## Recommended Reading Paths

### New Developer

1. [`../README.md`](../README.md)
2. [`operations/CONTRIBUTOR_WORKFLOW.md`](operations/CONTRIBUTOR_WORKFLOW.md)
3. [`operations/DEVELOPMENT_GUIDE.md`](operations/DEVELOPMENT_GUIDE.md)
4. [`architecture/SYSTEM_ARCHITECTURE.md`](architecture/SYSTEM_ARCHITECTURE.md)
5. [`architecture/CANONICAL_STRUCTURE.md`](architecture/CANONICAL_STRUCTURE.md)
6. [`../rules/project.md`](../rules/project.md)

### Working On Runtime Code

1. [`architecture/SYSTEM_ARCHITECTURE.md`](architecture/SYSTEM_ARCHITECTURE.md)
2. [`architecture/RUNTIME_EVENT_FLOW.md`](architecture/RUNTIME_EVENT_FLOW.md)
3. The subsystem doc under [`architecture/`](architecture/README.md), [`features/`](features/README.md), or [`hardware/`](hardware/README.md)
4. [`../AGENTS.md`](../AGENTS.md)
5. Relevant files under `yoyopod/`

### Working On Raspberry Pi Deployment

1. [`operations/CONTRIBUTOR_WORKFLOW.md`](operations/CONTRIBUTOR_WORKFLOW.md)
2. [`operations/SETUP_CONTRACT.md`](operations/SETUP_CONTRACT.md)
3. [`operations/DEV_PROD_LANES.md`](operations/DEV_PROD_LANES.md)
4. [`operations/SLOT_DEPLOY.md`](operations/SLOT_DEPLOY.md)
5. [`operations/PI_DEV_WORKFLOW.md`](operations/PI_DEV_WORKFLOW.md)
6. [`operations/RPI_SMOKE_VALIDATION.md`](operations/RPI_SMOKE_VALIDATION.md)

### Working On UI Or Design

1. [`design/README.md`](design/README.md)
2. [`architecture/DISPLAY_HAL_ARCHITECTURE.md`](architecture/DISPLAY_HAL_ARCHITECTURE.md)
3. [`architecture/INPUT_HAL_ARCHITECTURE.md`](architecture/INPUT_HAL_ARCHITECTURE.md)
4. [`architecture/CROSS_SCREEN_OVERLAYS.md`](architecture/CROSS_SCREEN_OVERLAYS.md)
5. [`../rules/design-fidelity.md`](../rules/design-fidelity.md)

### Working On Music, Voice, Or Cloud Features

1. [`features/README.md`](features/README.md)
2. [`features/LOCAL_FIRST_MUSIC_PLAN.md`](features/LOCAL_FIRST_MUSIC_PLAN.md)
3. [`features/CLOUD_VOICE_WORKER.md`](features/CLOUD_VOICE_WORKER.md)
4. [`features/CLOUD_PROVISIONING_AND_BACKEND.md`](features/CLOUD_PROVISIONING_AND_BACKEND.md)
5. [`hardware/AUDIO_STACK.md`](hardware/AUDIO_STACK.md)

## Current Contracts

These docs describe current implementation contracts:

- [`architecture/SYSTEM_ARCHITECTURE.md`](architecture/SYSTEM_ARCHITECTURE.md)
- [`architecture/CANONICAL_STRUCTURE.md`](architecture/CANONICAL_STRUCTURE.md)
- [`architecture/RUNTIME_EVENT_FLOW.md`](architecture/RUNTIME_EVENT_FLOW.md)
- [`architecture/DISPLAY_HAL_ARCHITECTURE.md`](architecture/DISPLAY_HAL_ARCHITECTURE.md)
- [`architecture/INPUT_HAL_ARCHITECTURE.md`](architecture/INPUT_HAL_ARCHITECTURE.md)
- [`operations/SETUP_CONTRACT.md`](operations/SETUP_CONTRACT.md)
- [`operations/QUALITY_GATES.md`](operations/QUALITY_GATES.md)
- [`operations/DEV_PROD_LANES.md`](operations/DEV_PROD_LANES.md)
- [`operations/SLOT_DEPLOY.md`](operations/SLOT_DEPLOY.md)
- [`hardware/POWER_MODULE.md`](hardware/POWER_MODULE.md)
- [`hardware/AUDIO_STACK.md`](hardware/AUDIO_STACK.md)
- [`features/CLOUD_PROVISIONING_AND_BACKEND.md`](features/CLOUD_PROVISIONING_AND_BACKEND.md)
- [`features/CLOUD_VOICE_WORKER.md`](features/CLOUD_VOICE_WORKER.md)
- [`features/REMOTE_PLAYBACK.md`](features/REMOTE_PLAYBACK.md)

## Historical Context

Use [`history/`](history/README.md), [`archive/`](archive/README.md), and [`superpowers/`](superpowers/README.md) when you need rationale or old implementation context. If they conflict with current code or current contracts, trust the current code and current contracts.
