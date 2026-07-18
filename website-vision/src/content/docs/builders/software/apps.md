---
title: App Platform
description: The parent app and future shared packages.
---

*The planned apps/ and packages/ layer: the parent app and the contracts it shares with the device.*

:::caution[Placeholder]
No as-built content exists for this page yet — the outline below is the target structure.
:::

## Overview

- The buyer's half of the product: parents manage from their phone, kids use the device
- Planned repository shape: `apps/` for the parent app, `packages/` for shared contracts
- What the parent app must carry for V1: whitelist calls and voice messages, live-ish location, setup
- Entirely future work — nothing in this layer exists yet

## Key components

- The parent mobile app (future) — product-facing outline at [Parent App](/apps/parent-app/)
- Shared `packages/`: types and contracts shared across app, cloud, and device (future)
- Pairing and setup flow inside the parent app — family-facing walkthrough at [Parent App Setup](/families/parent-app-setup/)
- The live-ish location view (future)

## Interfaces & contracts

- The app-to-cloud contract: shape and protocol (TBD)
- Shared packages as the single source of truth between app, cloud, and device (TBD)
- The whitelist editing flow: how a parent's change reaches the device
- The pairing contract between a new device and a family account (TBD)

## Today vs. target

- Today: this layer is entirely future work — `apps/` and `packages/` are planned directories, not present ones
- Today's device and cloud sides are documented in the as-built engineering docs (`website/` in the repository)
- Target: one parent app and one shared-contract layer, with no drift between them
- Platform and toolchain choices for the parent app (TBD)

## Open questions

- TODO: native, cross-platform, or web-wrapped parent app?
- TODO: what do shared packages compile to, so the Rust device side and the app side both consume them?
- TODO: does the parent app talk to the device only via the cloud, or also locally during setup?
