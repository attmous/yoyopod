---
title: "Setup: On-Device Onboarding"
description: First boot to paired-and-ready.
---

*The on-device onboarding that binds a new device to a family.*

:::caution[Vision stub]
Placeholder in the vision docs — the structure is decided, the content is
not written yet. As-built engineering docs live in the main docs site
(`website/` in the repository).
:::

## What it is

- The path from first boot to paired-and-ready, entirely on the small glass
- One of the four on-device screens (Hub, Listen, Talk, Setup) — a real screen today
- Designed for the kitchen-table moment right after [the unboxing](/families/unboxing/)
- Ends in exactly one state: bound to a family, connected, ready for a kid

## Key flows

- First boot: charge, power on, and what the glass shows first (TBD)
- Pairing: how the device and the family account meet (mechanism TBD)
- Connectivity bring-up: 4G registration and first contact with the cloud link
- Handover: the moment setup ends and the Hub wheel appears

## On the device

- The Setup screen: minimal steps navigable with one button and one small glass
- Progress and error states a parent can read without a manual (TBD)
- Re-entering Setup later for re-pairing or troubleshooting (TBD)

## In the parent app

- The mirrored half of pairing — [parent app setup](/families/parent-app-setup/) (the app itself is future work)
- Naming the device and the kid profile during pairing (TBD)
- What the parent sees confirmed once the device is bound (TBD)

## Status today

- Setup is a real on-device screen in the custom LVGL-based UI today
- The device-side cloud link (MQTT worker in the Rust runtime) exists — pairing will ride on it; see [the cloud link](/builders/software/cloud/)
- The parent-app half of pairing is future work
- The final pairing mechanism is not locked (TBD)

## Open questions

- TODO: What is the pairing mechanism given one button, no camera, and no browser on the device?
- TODO: How does setup behave with weak or no 4G coverage at first boot?
- TODO: Can a device be re-bound to a new family (resale, sibling handover)?
