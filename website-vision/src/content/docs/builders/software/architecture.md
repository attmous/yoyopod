---
title: Architecture at a Glance
description: "One diagram's worth of system: device, cloud, apps."
---

*The three-box picture — device, cloud, parent app — and what flows between them.*

## Overview

Three boxes. The **device** is one Rust supervisor process
(`yoyopod-runtime`) and its child worker processes, plus a custom
LVGL-based UI on the glass. The **cloud** is the device's line home: an
MQTT link and provisioning, owned by the device's cloud worker. The
**apps** box — the parent app and its shared packages — is future work:
planned directories, not present ones.

The device stays useful on its own: the media worker plays from the local
music library via mpv, the voip worker carries calls and voice notes via
liblinphone, and location reporting stays live-ish by design, never
real-time.

## Key components

| Box | What it is today |
| --- | --- |
| Device | `device/runtime/` supervising domain workers — media, voip, network, cloud, power, speech — and the UI host (`device/ui/`), all children of one process tree; see [Device Runtime & Workers](/builders/software/runtime/) and [UI System](/builders/software/ui/) |
| Cloud | the MQTT device link and provisioning, owned by `device/cloud/`; see [Cloud & Provisioning](/builders/software/cloud/) |
| Apps | **future** — planned `apps/` (parent app) and `packages/` (shared contracts); see [App Platform](/builders/software/apps/) |

Around the boxes sit `cli/` (the Rust operator CLI, rebuilding in rounds)
and `deploy/` (systemd units, installer scripts, slot/release packaging).

## Interfaces & contracts

- **Inside the device** — every message is one newline-framed JSON envelope with a strict schema stamp; mismatched peers fail closed at the first line. No sockets, no bus daemons — the process tree is the architecture.
- **Device ↔ cloud** — MQTT from `device/cloud/` to the backend, over the cellular modem owned by `device/network/`.
- **Boundary rules** — device runtime code must never depend on `apps/`; shared contracts should flow through `packages/contracts/` when that package exists (it is intended, not guaranteed present).
- **Configuration** — authored config is split by ownership under `config/` and composed into one typed runtime model, with an explicit secret boundary (tracked config may never contain SIP credentials) and board overlays (the only supported board is `rpi-zero-2w`).

## Today vs. target

- Today: the device box and the cloud link are real — runtime, workers, UI, MQTT transport, and provisioning all exist and are documented in depth in the as-built engineering docs (`website/` in the repository).
- Today: the apps box is empty by design — `apps/` and `packages/` are planned monorepo boundaries with their rules already written down.
- Prototype hardware today: Raspberry Pi Zero 2W + PiSugar Whisplay HAT.
- Target: the three-box picture stays the map as the apps layer lands.

## Open questions

- TODO: which protocol the parent app speaks to the cloud (REST, MQTT, something else)?
- TODO: one cloud box or two — does provisioning split from the device link on the diagram?
- TODO: where does the whitelist live authoritatively — device, cloud, or both?

:::note[Sources]
Condensed from [`docs/architecture/SYSTEM_ARCHITECTURE.md`](https://github.com/attmous/yoyopod/blob/main/docs/architecture/SYSTEM_ARCHITECTURE.md), [`docs/architecture/CANONICAL_STRUCTURE.md`](https://github.com/attmous/yoyopod/blob/main/docs/architecture/CANONICAL_STRUCTURE.md), and [`docs/architecture/WORK_AREAS.md`](https://github.com/attmous/yoyopod/blob/main/docs/architecture/WORK_AREAS.md), and the as-built docs site (`website/` in the repository): the runtime overview, Canonical Structure, and Work Areas pages.
:::
