---
title: "Setup: On-Device Onboarding"
description: First boot to paired-and-ready.
---

*The on-device onboarding that binds a new device to a family.*

:::tip[Proposed — the ideal design]
This page mixes as-built fact (covered by the Sources note) with the target
design, written out in full so it can be adopted, adapted, or dropped.
Everything marked *Proposed* is neither implemented nor committed.
:::

## What it is

Setup is the path from first boot to paired-and-ready, entirely on the
small canvas — designed for the kitchen-table moment right after
[the unboxing](/families/unboxing/). In the on-device navigation model it
is one of the root screens the whole UI stands on (alongside Hub, Listen,
Talk, and Ask), and it ends in exactly one state: bound to a family,
connected, ready for a kid.

## Key flows

*Proposed — the ideal design, not yet adopted.*

**First boot.** Charge it, press the button, and the canvas wakes with a
greeting and one job: getting this device into the family. There is no
Wi-Fi password to type and no account to create on the device — the yoyopod
brings up its own 4G connection quietly in the background while the
greeting is still on screen.

**Pairing.** The device shows a short code on the canvas. At the kitchen
table, the parent opens the yoyopod app and enters the code — or scans it
straight off the canvas. The app sends the code to yoyocloud; yoyocloud
checks that this device is showing that code right now and binds it to the
household. The phone and the device never talk to each other directly —
yoyocloud makes the match — which is why pairing needs nothing from the
device but its one button and its screen, and works the same whether the
phone is across the table or across the country.

**Connectivity bring-up.** Behind the code, the device registers on the
mobile network and makes first contact with yoyocloud over its own device
link. The canvas keeps this honest and small: a quiet indicator, not a wall
of status text. If coverage is weak at the table, the device keeps trying
on its own — setup is patient by design.

**Handover.** The moment yoyocloud confirms the binding, the canvas says so
— bound to the family, connected, ready — and the Hub wheel appears. Setup
never comes back unless the family asks it to: from here on, the device
belongs to a kid.

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

*Proposed — the ideal design, not yet adopted.*

The mirrored half of pairing is a short, warm walkthrough in the yoyopod
app — the family-facing version lives at
[parent app setup](/families/parent-app-setup/). A parent installs the app
(iOS or Android — a mixed-phone household is the normal case), signs in
with a passkey rather than a password, and the app creates the household. A
second parent joins the same household later, with equal say.

Then the app asks for exactly as much as pairing needs and no more: a first
name and an age band for the kid — that is the whole child profile, by
design — and a name for the device itself. Enter or scan the code from the
canvas, and the moment yoyocloud binds the device, the app shows it
confirmed: the device by name, its connection alive, ready.

The walkthrough ends by offering — not demanding — the three things worth
doing next: add the first few contacts to the whitelist, put some music and
stories on the device, and maybe build a first Help Agent for the Ask
wheel. Each can wait; the device is already whole. The full tour of what
the app can do lives at [Parent App](/apps/parent-app/).

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

- **Adopt canvas-code pairing as final.** A short code shown on the canvas,
  entered or scanned in the app, verified by yoyocloud — it needs no
  camera, no browser, and nothing but the one button on the device.
  Adopting it closes the pairing-mechanism question for good.
- **Adopt a weak-coverage story.** What the canvas says when 4G is thin at
  the kitchen table — keep trying quietly, suggest moving nearer a window,
  or let pairing complete later on its own — needs deciding before the
  first-boot screens are drawn.
- **Adopt first-class unclaiming in V1.** A server-side unbind and wipe
  that makes the device claimable again turns resale and hand-me-downs into
  ordinary events; deferring it makes them support tickets.
- **Adopt the minimal profile as a hard rule.** A first name and an age
  band, nothing more — the walkthrough should be structurally unable to ask
  for extra data, not merely polite enough not to.

:::note[Sources]
Condensed from
[`docs/features/CLOUD_PROVISIONING_AND_BACKEND.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/CLOUD_PROVISIONING_AND_BACKEND.md)
and the as-built docs site (`website/` in the repository): the Cloud
Provisioning & Backend feature page and the Screens & Navigation page.
:::
