# Operations Docs

Setup, deploy, and daily-workflow operations for YoYoPod on the Pi.

For the current state of the operator CLI and which capabilities are
temporarily paused, read [`../ROADMAP.md`](../ROADMAP.md) first.

## Active

- [`CONTRIBUTOR_WORKFLOW.md`](CONTRIBUTOR_WORKFLOW.md) - shortest
  contributor path from fresh checkout to a credible PR
- [`DEVELOPMENT_GUIDE.md`](DEVELOPMENT_GUIDE.md) - toolchain, running,
  validation, and daily workflow detail
- [`SETUP_CONTRACT.md`](SETUP_CONTRACT.md) - dev-machine + Pi setup
  prerequisites (manual today; full CLI bootstrap returns in a later
  round)
- [`QUALITY_GATES.md`](QUALITY_GATES.md) - what counts as
  pre-merge verification today
- [`DEV_PROD_LANES.md`](DEV_PROD_LANES.md) - dev/prod lane paths,
  systemd services, and lane activation
- [`PI_DEV_WORKFLOW.md`](PI_DEV_WORKFLOW.md) - day-to-day
  dev-machine-to-Pi loop via `yoyopod target …`

- [`PILLAR_VALIDATION.md`](PILLAR_VALIDATION.md) - ordered recovery and
  subsystem-isolation checks for uncertain hardware state

## Paused / in transition

These docs cover capabilities that are temporarily unavailable while
the operator CLI is being rebuilt in Rust. They return as the
corresponding round of the rebuild lands.

See [`archive/README.md`](archive/README.md). At a glance:

| File | Restored by |
|---|---|
| [`archive/RPI_SMOKE_VALIDATION.md`](archive/RPI_SMOKE_VALIDATION.md) | Round 2 |
| [`archive/PI_PROFILING_WORKFLOW.md`](archive/PI_PROFILING_WORKFLOW.md) | Round 2 + ongoing |
| [`archive/RELEASE_PROCESS.md`](archive/RELEASE_PROCESS.md) | Round 3 |
| [`archive/SLOT_DEPLOY.md`](archive/SLOT_DEPLOY.md) | Round 3 |
| [`archive/OTA_ROADMAP.md`](archive/OTA_ROADMAP.md) | Round 3 + later |

For hardware-specific dependencies and board notes, see
[`../hardware/README.md`](../hardware/README.md).
