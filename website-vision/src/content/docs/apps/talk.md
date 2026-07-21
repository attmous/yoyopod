---
title: "Talk: Calls & Voice Notes"
description: Contact-first calling and quick voice messages, whitelist only.
---

*The talking experience: contacts first, whitelist always, one button to speak.*

:::tip[Proposed — the ideal design]
This page mixes as-built fact (covered by the Sources note) with the target
design, written out in full so it can be adopted, adapted, or dropped.
Everything marked *Proposed* is neither implemented nor committed.
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

*Proposed — the ideal design, not yet adopted.*

**Call a favorite.** From the Hub wheel into Talk, and the canvas shows the
contact wheel: the people this family approved, each one a face and a name,
and nothing else. Spin to the right person, press to call. There is no
number pad and no address field anywhere on the device — calling a stranger
is not so much blocked as impossible to express. The whole ritual is the
story [Grandma calls](/stories/grandma-calls/).

**Receive a call.** When a whitelisted contact calls, the device rings and
the canvas is preempted: whatever the kid was doing steps aside, the music
pauses (a house rule in the runtime, not a setting), and the caller's name
and face fill the screen. One press answers; the call runs hands-free over
the built-in speaker and microphone. A call from anyone *not* on the
whitelist never rings, never shows, and leaves no missed-call trace — the
device refuses it before there is anything for a child to see.

**Send a voice note.** Hold the side button, talk, let go — the same
hold-to-talk grammar as everywhere else on the device
([using the button](/families/using-the-button/)). The moment the button is
released, the note is *sent* as far as the kid is concerned; behind the
scenes it travels store-and-forward through yoyocloud to the chosen
whitelisted contact — the yoyopod app on a parent's phone, or another
yoyopod in the family. If the device is offline (the school bus, the
basement), the note queues and goes when the link returns. The feeling this
is built for: [a voice note from the bus](/stories/voice-note-from-the-bus/).

**Find what's waiting.** A voice note that arrived while the kid was away
shows up in Talk as an unread mark on that contact — a small, findable
thing, not an interruption. Notes never auto-play; the kid opens the
contact and plays the note through the speaker when they choose, as many
times as they like. Missed calls from whitelisted contacts appear the same
way: on the contact, where a kid would naturally look.

## On the device

Talking belongs to the [VoIP Engine](/builders/software/voip-engine/):
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

*Proposed — the ideal design, not yet adopted.*

**The whitelist lives in the app.** Adding, removing, and naming contacts
is one of the yoyopod app's five V1 jobs, and the app is the only place the
list can be edited. A parent's change goes to yoyocloud first — the app
never talks to the device directly — and yoyocloud passes it to the device
as one whole, versioned list. The app then shows two honest states:
**saved** (yoyocloud has it) and **active on device** (the yoyopod
confirmed it is now enforcing it). If the device is offline, the change is
saved and applies the moment it reconnects — and until then, the device
keeps enforcing the last list it knew. Removing someone works the same way,
and the app says truthfully whether the device has heard about it yet. The
family-facing view of all this is
[Parental Controls](/families/parental-controls/).

**Parents are contacts too.** The yoyopod app is itself a whitelisted
destination: a kid's voice note can land on a parent's phone, and a parent
can hold to record a note back — same grammar, same store-and-forward relay
through yoyocloud, queuing patiently while either end is offline. For many
families this becomes the everyday channel: small voices arriving between
meetings.

**What parents see — and what they don't.** Voice notes sent within the
family are family-visible by design, and the app says so plainly rather
than hiding it. Live calls are different: they are not recorded and not
transcribed — a call between a kid and grandma stays between the kid and
grandma. Parents shape *who* can be reached; they do not listen in.

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

- **Adopt the cancel gesture.** Hold to record and release to send is
  settled; what is not is how a kid takes a note back — a brief undo moment
  after release, a slide-away gesture, or nothing at all. Decide before the
  replay screen is designed.
- **Adopt a ringing policy.** Always ring, or honor quiet hours a parent
  sets in the app? Scheduled windows would be a real sixth job beyond the
  app's five-job V1 scope — adopt it knowingly or drop it for V1.
- **Adopt the proposed voice-note limits as shipped defaults.** A
  60-second cap per note and a 30-day expiry for undelivered notes keep
  notes note-shaped and storage bounded; confirm them before the flows are
  built.
- **Adopt the visibility line.** Voice notes family-visible, live calls
  never recorded — a values decision that should be written down and stated
  plainly in the app, not discovered.

:::note[Sources]
Condensed from
[`docs/product/PRODUCT_DEFINITION.md`](https://github.com/attmous/yoyopod/blob/main/docs/product/PRODUCT_DEFINITION.md)
and the as-built docs site (`website/` in the repository): the VoIP worker
profile ("The Switchboard"), the Screens & Navigation page, and the
Product Definition page.
:::
