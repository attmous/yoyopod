---
title: The Parent App
description: "The companion mobile app: contacts, content, controls."
---

*The parent's side of yoyopod: everything managed from one phone app.*

:::caution[Partially filled]
Sections marked *Placeholder* have no as-built content yet; everything else is condensed from the repository (see Sources at the bottom).
:::

## What it is

*Placeholder — no as-built content yet.*

- One phone app for everything: contacts, content, controls, and reassurance
- The buyer-facing half of yoyopod: parents manage, kids simply use the device
- A companion, not a mirror — it manages the device rather than duplicating it
- The experience it must nail: [a parent's first week](/stories/first-week-parent/)

## Key flows

*Placeholder — no as-built content yet.*

- Pairing a new device into the family — [setup from the parent side](/families/parent-app-setup/)
- Contacts: build and edit the whitelist for calls and voice notes
- Content: load music and stories, curate playlists — [bedtime stories](/stories/bedtime-stories/)
- Controls: quiet hours, feature toggles, limits — [parental controls](/families/parental-controls/)
- Location glance and check-ins, kept deliberately live-ish

## On the device

*Placeholder — no as-built content yet.*

- What the kid notices when a parent changes something: a new contact appears, a new album arrives (TBD)
- Which settings the app owns versus the on-device Setup screen (TBD)
- Offline behavior: which app-made changes wait for connectivity (TBD)

## In the parent app

*Placeholder — no as-built content yet.*

- Home: at-a-glance device status — battery, connectivity, last check-in (TBD)
- Section structure: contacts, library, location, settings (TBD)
- Multi-parent and multi-device households (TBD)

## Status today

The app itself does not exist yet — but the device side it will talk to is
ready in places, and the build order is deliberate: device first, so the
app lands on a cloud link that already works.

- The device-side cloud link runs today: a provisioned device holds a
  device id and secret, connects over MQTT on per-device topics (events,
  acks, commands), publishes heartbeat, battery, and connectivity
  telemetry, and queues messages while offline.
- One backend-to-device contract is **validated on hardware**: remote
  playback — play, pause, resume, stop, and store-media commands with
  acks and lifecycle events — including importing an uploaded track into
  the device's local library.
- The claiming, household, and parent flows are owned by the backend and
  dashboard; the device never talks to the dashboard directly, it
  consumes provisioned secrets and the command channel.
- Not everything is wired yet: HTTP/REST sync, location telemetry, and
  richer backend command types are configured or backend-supported but
  not fully built — the intended surface, not the current one.

## Open questions

- TODO: Which platform ships first — and does V1 need both iOS and Android?
- TODO: How do two parents share control of one device without conflicts?
- TODO: What is the minimum app scope for V1, and what explicitly waits?

:::note[Sources]
Condensed from
[`docs/features/REMOTE_PLAYBACK.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/REMOTE_PLAYBACK.md)
and
[`docs/features/CLOUD_PROVISIONING_AND_BACKEND.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/CLOUD_PROVISIONING_AND_BACKEND.md)
and the as-built docs site (`website/` in the repository): the Remote
Playback and Cloud Provisioning & Backend feature pages.
:::
