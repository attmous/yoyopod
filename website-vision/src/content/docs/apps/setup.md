---
title: "Setup: On-Device Onboarding"
description: First boot to paired-and-ready.
---

*The on-device onboarding that binds a new device to a family.*

:::caution[Partially filled]
Sections marked *Placeholder* have no as-built content yet; everything else is condensed from the repository (see Sources at the bottom).
:::

## What it is

Setup is the path from first boot to paired-and-ready, entirely on the
small canvas — designed for the kitchen-table moment right after
[the unboxing](/families/unboxing/). In the on-device navigation model it
is one of the root screens the whole UI stands on (alongside Hub, Listen,
Talk, and Ask), and it ends in exactly one state: bound to a family,
connected, ready for a kid.

## Key flows

*Placeholder — no as-built content yet.*

- First boot: charge, power on, and what the canvas shows first (TBD)
- Pairing: how the device and the family account meet (mechanism TBD)
- Connectivity bring-up: 4G registration and first contact with the cloud link
- Handover: the moment setup ends and the Hub wheel appears

## On the device

The system surface exists on the canvas today as the Power screen, whose
normative design mockup is the setup mockup; the v5 UI contract replaces
it with a **Setup wheel** root. Underneath, the provisioning machinery is
real:

- Device identity is two runtime-only secrets — a device id and a device
  secret — stored in the device's cloud secrets config.
- The states are explicit: both secrets present means *provisioned*,
  neither means *unprovisioned*, and a partial pair means *invalid
  provisioning*.
- When provisioning is valid, the device runs its MQTT client on
  per-device topics — the cloud link Setup exists to establish; see
  [the cloud link](/builders/software/cloud/).

## In the parent app

*Placeholder — no as-built content yet.*

- The mirrored half of pairing — [parent app setup](/families/parent-app-setup/) (the app itself is future work)
- Naming the device and the kid profile during pairing (TBD)
- What the parent sees confirmed once the device is bound (TBD)

## Status today

- The provisioning flow exists and drives the cloud link today: a
  provisioned device connects over MQTT, publishes heartbeat, battery,
  and connectivity, and queues messages while offline.
- Claiming and household/parent flows are owned by the backend and
  dashboard — the device consumes provisioned secrets and the command
  channel, and never talks to the dashboard directly.
- On the canvas, the dedicated Setup wheel is part of the v5 contract but
  **staged, not shipped** — today's screen is the Power screen it
  replaces.
- The parent-app half of pairing is future work, and the final pairing
  mechanism is not locked.

## Open questions

- TODO: What is the pairing mechanism given one button, no camera, and no browser on the device?
- TODO: How does setup behave with weak or no 4G coverage at first boot?
- TODO: Can a device be re-bound to a new family (resale, sibling handover)?

:::note[Sources]
Condensed from
[`docs/features/CLOUD_PROVISIONING_AND_BACKEND.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/CLOUD_PROVISIONING_AND_BACKEND.md)
and the as-built docs site (`website/` in the repository): the Cloud
Provisioning & Backend feature page and the Screens & Navigation page.
:::
