---
title: Dev Environment
description: Toolchain and repo orientation.
---

*From clean machine to building the workspace.*

:::caution[Vision stub]
Placeholder in the vision docs — the structure is decided, the content is
not written yet. As-built engineering docs live in the main docs site
(`website/` in the repository).
:::

## Overview

- Who this page is for: a contributor with a clean machine who wants a first successful build
- What "set up" means here: toolchain installed, repo cloned, workspace builds on the host
- What this page does not cover: flashing hardware — that lives at [Build & Flash a Device](/builders/dev/build-and-flash/)
- The repository: https://github.com/attmous/yoyopod

## Toolchain

- Rust toolchain as the core requirement — the device runtime and workers are Rust
- Host-side build first: everything a contributor needs before touching hardware
- Cross-compilation targets for the prototype board (Raspberry Pi Zero 2W) — exact target setup steps (TBD)
- Supporting tools for the docs sites and any host tooling (TBD which are required vs. optional)
- Minimum supported host platforms (TBD)

## Repo orientation

- `device/` — the Rust workspace: runtime, domain workers, and the LVGL-based UI
- `cli/` — the developer command-line tool, built separately from the device workspace
- `website/` — the as-built engineering docs site
- `website-vision/` — this site: target-state and vision docs
- Planned but not yet present: `apps/` (parent app) and `packages/` (SDKs) — future work
- A guided tour of where each subsystem lives, mapped to [Software Architecture](/builders/software/architecture/)

## Today vs. target

- Today: host builds of the Rust workspace and CLI are the daily loop
- Today: hardware setup targets the prototype path (Pi Zero 2W + PiSugar Whisplay HAT)
- Target: a documented, scripted from-zero setup that a new contributor can finish in one sitting (TBD)
- Target: environment story for the future `apps/` and `packages/` directories once they exist

## Open questions

- TODO: What is the officially supported host OS matrix for contributors (Windows, macOS, Linux)?
- TODO: Should cross-compilation be documented here or deferred entirely to the build-and-flash page?
- TODO: Which toolchain versions do we pin, and where is the single source of truth for them?
