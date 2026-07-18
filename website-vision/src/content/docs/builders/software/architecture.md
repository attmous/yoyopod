---
title: Architecture at a Glance
description: "One diagram's worth of system: device, cloud, apps."
---

*The three-box picture — device, cloud, parent app — and what flows between them.*

:::caution[Vision stub]
Placeholder in the vision docs — the structure is decided, the content is
not written yet. As-built engineering docs live in the main docs site
(`website/` in the repository).
:::

## Overview

- The three boxes: the device in a kid's pocket, the cloud in the middle, the parent app in a parent's hand
- One sentence of responsibility per box — what each owns, what it refuses to own
- Why the device stays useful when the middle box is unreachable: music and stories are local-first
- The V1 boundary drawn on the picture: whitelist calls, voice messages, live-ish location

## Key components

- Diagram box: device — Rust runtime supervising domain workers, custom LVGL-based UI on the glass (see [Device Runtime & Workers](/builders/software/runtime/))
- Diagram box: cloud — device link and provisioning today, parent-facing backend surface later (see [Cloud & Provisioning](/builders/software/cloud/))
- Diagram box: parent app — future work, planned `apps/` directory (see [App Platform](/builders/software/apps/))
- Arrow: device ↔ cloud — MQTT over the 4G modem
- Arrow: cloud ↔ parent app — API surface, shape (TBD)
- Arrow: parent settings → device policy — how whitelist changes travel (TBD)

## Interfaces & contracts

- The device-to-cloud contract: topics, payloads, and what may never cross the link (TBD)
- The cloud-to-app contract: planned shared `packages/` as the single source of shared types
- Location semantics annotated on the diagram: live-ish by design, never real-time
- What is deliberately absent from every box: no camera, no browser, no app store

## Today vs. target

- Today: device runtime, workers, UI, and the MQTT cloud link exist; parent app and `packages/` are future work
- The as-built engineering docs (`website/` in the repository) carry the full UI System and Runtime & Workers guides
- Prototype hardware today: Raspberry Pi Zero 2W + PiSugar Whisplay HAT; a product board may replace it (TBD)
- Target: the three-box diagram drawn once here and kept current as the layers land

## Open questions

- TODO: which protocol the parent app speaks to the cloud (REST, MQTT, something else)?
- TODO: one cloud box or two — does provisioning split from the device link on the diagram?
- TODO: where does the whitelist live authoritatively — device, cloud, or both?
