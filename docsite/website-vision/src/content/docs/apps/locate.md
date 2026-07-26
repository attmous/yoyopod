---
title: "Locate: Location & Check-Ins"
description: Live-ish location awareness for peace of mind.
---

*The location experience — deliberately "live-ish", deliberately not surveillance.*

:::tip[Proposed — the ideal design]
This page is the target design, written out in full so it can be adopted,
adapted, or dropped. Everything on it is proposed — neither implemented
nor committed.
:::

## What it is

Locate answers one small, recurring parental question — *is my kid
roughly where I expect them to be?* — and refuses to answer any bigger
one. A parent opens the yoyopod app and sees a map with a single dot and
a timestamp: where the device last reported, and exactly when. That is
the whole feature, and the restraint is the point.

We call it **live-ish** because that is what it honestly is: the device
sends a position fix every so often — periodic and coarse, not a
continuous stream — and the app shows the most recent one with its age
written plainly beside it. "Live-ish" is not marketing hedge-language
around a tracking feed we secretly wish were real-time; it is a design
decision that there should be no real-time feed at all. Peace of mind
comes from *as of 8:47, near the school* — it does not require watching
a dot crawl down a street.

The line we draw is reassurance versus surveillance. Locate exists so a
parent can stop worrying and get back to their day, not so they can
follow every step of a walk. A kid who knows they are trusted to make
the trip — and knows the device is honest with them about what it
shares — is the outcome we are building for. The defining scene is
[Mia's walk to school](/stories/mia-walk-to-school/): a glance, a
timestamp, a breath out.

## Key flows

**The glance check.** A parent opens the yoyopod app, taps into the
location view, and sees the last reported position with a freshness
stamp — "as of 12 minutes ago." If the most recent fix is old, the app
says so in plain words instead of showing a confident dot. No animation,
no extrapolated movement, no "arriving in 3 minutes" guesses. The map
never pretends to know more than it does.

**The check-in.** Sometimes the kid wants to say *I'm here* — arriving
at school, reaching Grandma's door, getting off the bus. On the device,
they spin to Locate on the wheel, hold the button, and the device sends
a fresh fix along with a friendly check-in note to the parent's app.
It is the kid's gesture, made on purpose, the same hold-the-button
motion they already know from everything else on the device. A check-in
is a moment of connection, not a compliance report.

**Where the feature stops — on purpose.** There is no route history to
scrub through, no geofence alarms, no "left the safe zone" sirens, no
minute-by-minute breadcrumb trail. Arrived-safely reassurance is the
job; continuous tracking is a different product, one we decline to
build. The fuller family-facing promise lives at
[how families see location](/families/location/).

**Transparency toward the kid.** The device never hides that location
is on. Locate has its own place on the wheel precisely so the kid can
see it, visit it, and understand it. A device that quietly reports on
its owner teaches the wrong lesson about every device that comes after
it.

## On the device

The hardware does the honest minimum. GPS and the cellular modem
together produce a position fix on a gentle cadence — often enough that
the newest fix is useful, rarely enough that the battery lives a full
day of listening and talking without complaint. Fixes are coarse by
design: "near the school," not "third paving stone from the gate."

On the canvas, Locate shows a small, truthful status rather than a map:
whether location sharing is on, and when the device last shared. There
is no kid-facing map, no tracking screen, no way for the device to
become a toy compass for watching oneself move — the canvas stays calm.
The one active thing a kid can do here is the check-in: hold the
button, send *I'm here*, see a small confirmation, done.

The modem, GPS, and their power budget are engineering territory —
covered at [Connectivity](/builders/hardware/connectivity/).

## In the parent app

The location view is one of the yoyopod app's five jobs, and it is
deliberately quiet. It shows the map, the last fix, and the freshness
stamp, and it fetches the newest fix when the parent opens it; when a
check-in arrives, a notification taps the parent on the shoulder. There
is no always-open live channel, because the product makes no live
promise — the app pulls when you look, and nudges you when your kid has
something to say.

Check-in notifications are gentle by default: a check-in rings through,
routine position updates never do. The app informs; it does not nag.

History is nearly absent on purpose. yoyocloud keeps only the latest
passive fix, briefly, and deletes it when the next one replaces it; the
one thing that lingers a few days is a check-in the kid deliberately
sent — enough to answer "did she check in this morning?", never enough
to reconstruct a childhood of movements. The reasoning is spelled out in the
[privacy stance](/families/privacy/). How fixes travel from the device
through the backbone to the app is documented at
[Cloud & Provisioning](/builders/software/cloud/).

## Status today

The ingredients exist; the dish is not yet cooked. GPS and the 4G modem
are on the prototype hardware, and a network worker already runs in the
device's runtime. But position reporting is not yet wired end to end —
the device does not yet publish fixes over its cloud link — and the
parent-app map view is future work, as the yoyopod app itself does not
exist yet. The retention policy above is a proposal awaiting a
decision, not a shipped setting. Everything on this page describes the
target experience those pieces are being built toward.

## Open questions

- **Adopt a concrete cadence?** Pick the fix interval that earns "live-ish" — frequent enough for the glance check, sparse enough to protect a full day of battery — and write it down as a number, not a vibe.
- **Adopt kid-initiated check-in as the only check-in for V1?** The hold-the-button *I'm here* is simple and honest; arrival-triggered automatic check-ins are more convenient but edge toward surveillance — decide which ships, or whether both do.
- **Adopt the retention split?** Latest passive fix only (gone when replaced) plus a few days for deliberate check-ins — confirm the numbers and make them the shipped setting.
- **Adopt the canvas transparency cue as designed?** Locate on the wheel showing sharing status and last-shared time is the kid-facing honesty story — confirm it, or design a stronger one.
