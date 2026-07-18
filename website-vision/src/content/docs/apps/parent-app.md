---
title: The Parent App
description: "The companion mobile app: contacts, content, controls."
---

*The parent's side of yoyopod: everything managed from one phone app.*

:::caution[Vision stub]
Placeholder in the vision docs — the structure is decided, the content is
not written yet. As-built engineering docs live in the main docs site
(`website/` in the repository).
:::

## What it is

- One phone app for everything: contacts, content, controls, and reassurance
- The buyer-facing half of yoyopod: parents manage, kids simply use the device
- A companion, not a mirror — it manages the device rather than duplicating it
- The experience it must nail: [a parent's first week](/stories/first-week-parent/)

## Key flows

- Pairing a new device into the family — [setup from the parent side](/families/parent-app-setup/)
- Contacts: build and edit the whitelist for calls and voice notes
- Content: load music and stories, curate playlists — [bedtime stories](/stories/bedtime-stories/)
- Controls: quiet hours, feature toggles, limits — [parental controls](/families/parental-controls/)
- Location glance and check-ins, kept deliberately live-ish

## On the device

- What the kid notices when a parent changes something: a new contact appears, a new album arrives (TBD)
- Which settings the app owns versus the on-device Setup screen (TBD)
- Offline behavior: which app-made changes wait for connectivity (TBD)

## In the parent app

- Home: at-a-glance device status — battery, connectivity, last check-in (TBD)
- Section structure: contacts, library, location, settings (TBD)
- Multi-parent and multi-device households (TBD)

## Status today

- The app is future work: a planned apps/ directory in the repository, not yet started
- The device-side cloud link exists: an MQTT-based worker in the Rust runtime runs today
- Device-first build order: the app will land on a cloud link that already works
- Platform and stack choice: not yet decided (TBD)

## Open questions

- TODO: Which platform ships first — and does V1 need both iOS and Android?
- TODO: How do two parents share control of one device without conflicts?
- TODO: What is the minimum app scope for V1, and what explicitly waits?
