---
title: "Talking: Calls & Voice Notes"
description: Whitelist calls and quick voice messages to approved contacts.
---

*How a kid calls family and sends voice notes — and why only the whitelist gets through.*

:::tip[Proposed — the ideal design]
This page mixes as-built fact (covered by the Sources note) with the target
design, written out in full so it can be adopted, adapted, or dropped.
Everything marked *Proposed* is neither implemented nor committed.
:::

## What you'll need

The one thing Talk truly needs is a **whitelist**: the short list of
people a parent has approved. Talk is contact-first — a kid picks a
*person*, never dials a number — and the whitelist works in both
directions. Only approved contacts can call the device, and the device
can only call approved contacts. Whitelist calls and voice messages are
the first pillar of the whole product; reliable reachability is one of
the two trust anchors everything else is built on.

An honest status check, so this page doesn't promise more than exists:

- **Calling** is real on the device — there are screens for picking a
  contact, for an incoming call, an outgoing call, and being in a call —
  but it is still being validated on real hardware. It is not something
  a family can rely on day to day yet.
- **Voice notes** are designed (hold the button, speak, release — like a
  walkie-talkie) but **not built yet**. The Talk screens for recording
  and replaying voice messages are still on the drawing board.
- The parent app that would manage the whitelist is also still ahead of
  us, so today contacts are set up by the development team, not from a
  phone.

## Steps

*Proposed — the ideal design, not yet adopted.*

**Calling someone.** From the home wheel, roll to [Talk](/apps/talk/)
and double-press in. Talk is a small wheel of people — every contact a
parent has approved, each name spoken aloud as it rolls by, and nobody
else, ever. Double-press a person and the call starts, hands-free
through the built-in speaker and microphone: no headphones, nothing held
to an ear. When a call comes *in*, the device makes it unmissable — the
music pauses, the caller's name takes over the canvas, and the kid
answers or declines with the button. For the whole warm loop of it, read
[Grandma calls](/stories/grandma-calls/).

**Sending a voice note.** Pick the person in Talk, then hold the side
button and speak — walkie-talkie style, the same
[hold-to-talk](/families/using-the-button/) the device uses everywhere.
Release, and the note is on its way: delivered to that person's yoyopod
app, or to another yoyopod in the family. If the device has no bars at
that moment, nothing is lost — the note waits on the device and sends
itself the moment coverage returns. As far as the kid is concerned, it
was sent the instant their thumb lifted. See
[a voice note from the bus](/stories/voice-note-from-the-bus/).

**Receiving a voice note.** A new note appears in Talk as an unread
item — the device announces it without barging in, and notes never play
themselves. The kid opens Talk, plays the note when ready, and can play
it again as many times as a good message deserves.

## Tips

*Proposed — the ideal design, not yet adopted.*

The whitelist works in both directions, and that is the whole point: a
stranger does not reach a busy signal or a voicemail — they simply have
no way to ring this device at all. Keep the list short and deeply
familiar: family first, then the two or three grown-ups who are
practically family. A short list a kid knows by heart beats a long one
they scroll past.

Practice the walkie-talkie hold at the kitchen table before the first
real errand — hold, speak, release, done. Thirty seconds of practice
turns the side button into muscle memory.

And let voice notes carry the small stuff. "I'm here," "running late,"
"found my shoe" — a note asks nothing of the other person's moment,
which is exactly why kids end up sending more of them.

## Troubleshooting

*Proposed — the ideal design, not yet adopted.*

**A call won't connect.** A live call needs coverage right now — check
the bars on the device first. If coverage is fine, check the whitelist
in the yoyopod app: calls only work between approved contacts, in both
directions.

**No bars at all.** Calls will wait, but voice notes are never lost: a
note recorded with no coverage queues on the device and sends itself
when the bars come back — the kid never has to remember to retry. Notes
headed *to* the device wait for it the same way.

**"I tried to call and couldn't get through."** When a relative says
this, it is almost always the whitelist doing its job: they are not on
it. Add them in the yoyopod app — and note that the app shows the
difference between a change that is *saved* and one that is *active on
the device*, so you know exactly when Grandma's first call will ring
through.

**The other side can't hear well.** Calls are hands-free: face the
device, keep hands away from the microphone opening, and step somewhere
quieter — the speaker and microphone are built for a kitchen table, not
a school fair.

## Open questions

- Adopt parent-set quiet hours — windows when incoming calls wait as missed instead of ringing — or ring always in V1 “Daylight”?
- Adopt plain phone numbers as whitelisted contacts, so a grandparent needs no app at all, or keep V1 “Daylight” to the yoyopod app and other yoyopods?
- Adopt a cancel gesture for a mis-held voice note, or keep the grammar strictly hold–speak–release and let short accidental notes be harmless?
- Adopt a parent-set call-length limit as part of [parental controls](/families/parental-controls/), or leave call time unlimited?

:::note[Sources]
Condensed from
[`docs/product/PRODUCT_DEFINITION.md`](https://github.com/attmous/yoyopod/blob/main/docs/product/PRODUCT_DEFINITION.md)
and
[`docs/ROADMAP.md`](https://github.com/attmous/yoyopod/blob/main/docs/ROADMAP.md)
and the as-built docs site (website/ in the repository): the Product
Definition and Roadmap pages and the UI guide's navigation page (Screens
& Navigation).
:::
