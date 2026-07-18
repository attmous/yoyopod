---
title: "Talk: Calls & Voice Notes"
description: Contact-first calling and quick voice messages, whitelist only.
---

*The talking experience: contacts first, whitelist always, one button to speak.*

:::caution[Partially filled]
Sections marked *Placeholder* have no as-built content yet; everything else is condensed from the repository (see Sources at the bottom).
:::

## What it is

Whitelist calls and voice messages are **pillar one** of the product:
kids reach the people their parents approved, and nobody else. Talk is
contact-first — names on the canvas, never a number pad, never an unknown
caller. Reliable reachability is one of the two trust anchors the whole
product stands on, which is why safe communication gets the largest
engineering investment on the device.

The family-facing view of talking lives at [Talking](/families/talking/).

## Key flows

*Placeholder — no as-built content yet.*

- Call a favorite: from the Hub wheel into Talk, pick a contact, call — [Grandma calls](/stories/grandma-calls/)
- Send a voice note: hold the side button to talk, release to send — [a voice note from the bus](/stories/voice-note-from-the-bus/)
- Receive: what an incoming call or voice note looks and sounds like (TBD)
- Missed things: how a kid finds and replays a waiting voice note (TBD)

## On the device

Talking belongs to the [Calling Engine](/builders/software/calling-engine/):
the voip worker — "the switchboard" — the largest
worker in the Rust runtime at roughly 5,600 lines. It wraps a native
**liblinphone** core through a hand-rolled FFI shim and owns the entire
communication surface: SIP registration, call control, text and voice-note
messaging, call history, and voice-note record and playback.

- Registration tracks recovery explicitly: a re-registration after a
  failure is reported as *recovered*, not merely *registered*, so a clean
  start and a comeback are distinguishable.
- Calls move through 13 states; an incoming call preempts whatever screen
  the kid is on, and a house rule in the runtime pauses the music.
- Call and capture audio run hands-free through the built-in speaker and
  microphone over the device's audio hardware.
- Messaging keeps a small persistent store with per-contact unread
  summaries, and voice notes have their own recording session lifecycle
  (idle, recording, recorded, sending).

## In the parent app

*Placeholder — no as-built content yet.*

- Parents manage the whitelist: add, remove, and name contacts (future)
- Contact changes reach the device over the cloud link (TBD)
- What parents see about call activity, and what stays between kid and contact (TBD)

## Status today

- The voip worker exists and is the most substantial in the runtime, but
  Talk is **staged**: end-to-end device-to-phone call validation is still
  incomplete, and a recent on-hardware run logged recovery warnings from
  an unavailable liblinphone backend.
- Voice-note machinery exists at the worker level (record, send, replay
  commands and a session lifecycle), but the kid-facing flow is not built
  end to end: the v5 UI contract retires the standalone voice-note screen,
  moves capture into the contact screen with push-to-talk passthrough, and
  adds a new replay screen that does not exist yet.
- On the canvas, the Talk root becomes the contact wheel in the v5
  contract, folding the separate contacts and call-history screens away.
- Whitelist management waits on the parent app (future work).

## Open questions

- TODO: What is the exact push-to-talk grammar (hold to record, release to send, how to cancel)?
- TODO: When does the device ring — always, quiet hours, parent-scheduled windows?
- TODO: Where do voice notes queue when the device is offline, and for how long?

:::note[Sources]
Condensed from
[`docs/product/PRODUCT_DEFINITION.md`](https://github.com/attmous/yoyopod/blob/main/docs/product/PRODUCT_DEFINITION.md)
and the as-built docs site (`website/` in the repository): the VoIP worker
profile ("The Switchboard"), the Screens & Navigation page, and the
Product Definition page.
:::
