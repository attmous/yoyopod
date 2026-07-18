---
title: Cloud & Provisioning
description: Backend, provisioning, and the device's cloud link.
---

*How a device gets an identity, a SIM, and a safe line home.*

:::caution[Vision stub]
Placeholder in the vision docs — the structure is decided, the content is
not written yet. As-built engineering docs live in the main docs site
(`website/` in the repository).
:::

## Overview

- A device's life story with the cloud: identity first, then a SIM, then a safe line home
- The line home today: MQTT over the 4G modem, owned by the cloud worker
- What the cloud never needs to see: local-first music and stories stay on the device
- The parent-app-facing backend surface is future work

## Key components

- Device identity: how a device becomes provably "this device" (mechanism TBD)
- SIM and 4G provisioning path
- The MQTT cloud link (exists today)
- Parent-app-facing backend surface (future)

## Interfaces & contracts

- Device ↔ cloud topics and payload shapes (outline; TBD)
- The provisioning handshake: from blank device to owned-by-a-family (TBD)
- Location reporting cadence: live-ish by design, never real-time
- The contracts a future parent app consumes, via planned shared `packages/` (see [App Platform](/builders/software/apps/))

## Today vs. target

- Today: the MQTT link and provisioning exist on the device side
- Today's cloud worker is covered in the as-built Runtime & Workers Guide in the engineering docs (`website/` in the repository)
- Target: a parent-app-facing backend surface — entirely future work
- Target: provisioning documented end to end, factory through family setup

## Open questions

- TODO: which provisioning steps happen at the factory vs. in a parent's hands?
- TODO: broker topology for the MQTT link — managed service or self-hosted (TBD)?
- TODO: how does a device change families — resale, hand-me-down to a sibling?
