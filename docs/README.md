# YoYoPod Documentation

This page is the entry point for repo documentation.

If you are new here:

1. [`../README.md`](../README.md) for the repo overview and quick start
2. [`ROADMAP.md`](ROADMAP.md) for the current rebuild state — which CLI
   commands work today and which are paused
3. [`operations/DEVELOPMENT_GUIDE.md`](operations/DEVELOPMENT_GUIDE.md) for setup, running, validation, and daily workflow
4. [`architecture/SYSTEM_ARCHITECTURE.md`](architecture/SYSTEM_ARCHITECTURE.md) for the current runtime shape

## Source Of Truth

When docs disagree, trust sources in this order:

1. Current Rust runtime and worker host code in `device/`
2. Current Rust operator CLI in `cli/` and deploy tooling under `deploy/`
3. [`ROADMAP.md`](ROADMAP.md) — what's currently broken or paused
4. Current operations, architecture, hardware, features, and design
   docs in the folders below
5. Rules and agent guidance in [`../rules/`](../rules/),
   [`../AGENTS.md`](../AGENTS.md), and [`../skills/`](../skills/)

The repo is Rust-only end to end. The retired Python app runtime and
the Python operator CLI have both been deleted. Plan docs are useful
context, but they are not automatically the current implementation
contract.

## Folder Map

- [`architecture/`](architecture/README.md) — runtime topology,
  package/config ownership, event flow
- [`operations/`](operations/README.md) — contributor workflow, setup,
  quality gates, dev/prod lanes, daily Pi workflow
- [`operations/archive/`](operations/archive/README.md) — paused
  capability docs (release pipeline, slot deploy, OTA, hardware
  validation, profiling) — return as rebuild rounds land
- [`hardware/`](hardware/README.md) — audio and power module
  integration notes for Pi Zero 2W + Whisplay + PiSugar
- [`features/`](features/README.md) — cloud provisioning, cloud voice,
  local music, mpv, and remote playback contracts
- [`design/`](design/README.md) — UI design targets and visual previews
- [`product/`](product/README.md) — product definition and positioning
- [`assets/`](assets/) — images and media used in docs

## Recommended Reading Paths

### New Developer

1. [`../README.md`](../README.md)
2. [`ROADMAP.md`](ROADMAP.md)
3. [`operations/CONTRIBUTOR_WORKFLOW.md`](operations/CONTRIBUTOR_WORKFLOW.md)
4. [`operations/DEVELOPMENT_GUIDE.md`](operations/DEVELOPMENT_GUIDE.md)
5. [`architecture/SYSTEM_ARCHITECTURE.md`](architecture/SYSTEM_ARCHITECTURE.md)
6. [`../rules/project.md`](../rules/project.md)

### Working On Runtime Or Worker Code

1. [`architecture/WORK_AREAS.md`](architecture/WORK_AREAS.md)
2. [`architecture/SYSTEM_ARCHITECTURE.md`](architecture/SYSTEM_ARCHITECTURE.md)
3. [`architecture/RUNTIME_EVENT_FLOW.md`](architecture/RUNTIME_EVENT_FLOW.md)
4. The subsystem doc under
   [`features/`](features/README.md) or
   [`hardware/`](hardware/README.md)
5. [`../AGENTS.md`](../AGENTS.md)
6. Relevant files under `device/`

### Working On The Rust CLI

1. [`ROADMAP.md`](ROADMAP.md)
2. [`../cli/README.md`](../cli/README.md)
3. Relevant files under `cli/yoyopod/src/`

### Working On Raspberry Pi Deployment

1. [`ROADMAP.md`](ROADMAP.md)
2. [`operations/CONTRIBUTOR_WORKFLOW.md`](operations/CONTRIBUTOR_WORKFLOW.md)
3. [`operations/SETUP_CONTRACT.md`](operations/SETUP_CONTRACT.md)
4. [`operations/DEV_PROD_LANES.md`](operations/DEV_PROD_LANES.md)
5. [`operations/PI_DEV_WORKFLOW.md`](operations/PI_DEV_WORKFLOW.md)
6. Paused docs in [`operations/archive/`](operations/archive/README.md)
   when their subject matter is your blocker

### Working On UI Or Design

1. [`design/README.md`](design/README.md)
2. [`../rules/design-fidelity.md`](../rules/design-fidelity.md)
3. [`../rules/lvgl.md`](../rules/lvgl.md)
4. Relevant files under `device/ui/`

### Working On Music, Voice, Or Cloud Features

1. [`features/README.md`](features/README.md)
2. [`features/LOCAL_FIRST_MUSIC_PLAN.md`](features/LOCAL_FIRST_MUSIC_PLAN.md)
3. [`features/CLOUD_VOICE_WORKER.md`](features/CLOUD_VOICE_WORKER.md)
4. [`features/CLOUD_PROVISIONING_AND_BACKEND.md`](features/CLOUD_PROVISIONING_AND_BACKEND.md)
5. [`hardware/AUDIO_STACK.md`](hardware/AUDIO_STACK.md)

## Current Contracts

Authoritative implementation contracts as of today:

- [`ROADMAP.md`](ROADMAP.md)
- [`architecture/SYSTEM_ARCHITECTURE.md`](architecture/SYSTEM_ARCHITECTURE.md)
- [`architecture/WORK_AREAS.md`](architecture/WORK_AREAS.md)
- [`architecture/CANONICAL_STRUCTURE.md`](architecture/CANONICAL_STRUCTURE.md)
- [`architecture/RUNTIME_EVENT_FLOW.md`](architecture/RUNTIME_EVENT_FLOW.md)
- [`operations/CONTRIBUTOR_WORKFLOW.md`](operations/CONTRIBUTOR_WORKFLOW.md)
- [`operations/DEVELOPMENT_GUIDE.md`](operations/DEVELOPMENT_GUIDE.md)
- [`operations/SETUP_CONTRACT.md`](operations/SETUP_CONTRACT.md)
- [`operations/QUALITY_GATES.md`](operations/QUALITY_GATES.md)
- [`operations/DEV_PROD_LANES.md`](operations/DEV_PROD_LANES.md)
- [`operations/PI_DEV_WORKFLOW.md`](operations/PI_DEV_WORKFLOW.md)
- [`operations/PILLAR_VALIDATION.md`](operations/PILLAR_VALIDATION.md)
- [`hardware/POWER_MODULE.md`](hardware/POWER_MODULE.md)
- [`hardware/AUDIO_STACK.md`](hardware/AUDIO_STACK.md)
- [`features/CLOUD_PROVISIONING_AND_BACKEND.md`](features/CLOUD_PROVISIONING_AND_BACKEND.md)
- [`features/CLOUD_VOICE_WORKER.md`](features/CLOUD_VOICE_WORKER.md)
- [`features/REMOTE_PLAYBACK.md`](features/REMOTE_PLAYBACK.md)

## Historical Context

Historical planning archives were removed from the tracked repo. Use
merged PRs, [`ROADMAP.md`](ROADMAP.md), and current docs for rationale;
when docs disagree, trust current code.
