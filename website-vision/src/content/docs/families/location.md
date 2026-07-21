---
title: Location & Check-Ins
description: Live-ish location for peace of mind — what it is and isn't.
---

*What parents see on the map, how fresh it is, and what a check-in means.*

:::tip[Proposed — the ideal design]
This page is the target design, written out in full so it can be adopted,
adapted, or dropped. Everything on it is proposed — neither implemented
nor committed.
:::

## What you'll need

Three things: a paired device with location sharing switched on by a
parent, [the yoyopod app](/apps/parent-app/) — the map lives there and
nowhere else — and a route with some sky and signal on it. Location is a
parent decision from the start: it does nothing until a parent turns it
on, and everything it shows, it shows only inside the family's own app.

## Steps

Open the yoyopod app and go to the map. What you see is deliberately
simple: one dot per kid, and a small timestamp under the dot —
"4 minutes ago." That timestamp is the honest heart of the whole
feature. The device reports its position every few minutes, in broad
strokes; the app fetches the newest fix when you open it, and a
notification nudges it awake when something worth a look arrives, such
as a check-in.

Here is the honest explanation, in parent words: **the dot is a recent
snapshot, not a live wire.** Location on yoyopod is live-ish — updated
every few minutes, roughly where rather than exactly where. That is a
design choice, not a corner cut. It answers the question parents
actually have — *is she about where she should be, about now?* — on a
fraction of the battery, and without turning a childhood into a line on
a map. When the question is truly "right now," the honest tool is a
call, not a map.

**Check-ins.** A check-in is the kid's half of the conversation: an
"I'm here," sent on purpose. On the device, the kid rolls to
[Locate](/apps/locate/) on the home wheel and holds the button; the
device sends its current spot, flagged as sent deliberately. On the
parent's phone it lands as a notification — name, place, time — and it
reads very differently from a dot you went looking for: it is the knock
on the door that says *made it*. For how this feels on a real morning,
read [Mia's walk to school](/stories/mia-walk-to-school/).

**What location is not.** There is no continuous track. The device does
not record a breadcrumb trail of a kid's day, and neither does the app:
no route replay, no history page, nothing to scroll back through. Fixes
are kept only briefly — long enough to show the latest one — and then
deleted, so yesterday's walk to school exists nowhere. The map answers
*about where, about now*, and deliberately nothing more. The fuller
version of that promise lives at
[Our Privacy Promise](/families/privacy/).

## Tips

Trust the timestamp more than the dot. A fresh timestamp with a
plausible dot is good news; an old timestamp means the device has not
been able to report for a while — usually indoors or a coverage dip —
not that something is wrong.

Talk about the map with the kid. They should know exactly what parents
can see and how often — that openness is what keeps the map a comfort
inside the family rather than a secret hanging over it.

Teach the check-in habit. It beats map-watching for both sides: the kid
owns the message, and the parent gets certainty instead of inference.

And let the map be boring. In a good week you will barely open it — a
quiet map is the feature working, not the feature failing.

## Troubleshooting

**The dot hasn't moved in a while.** Read the timestamp before worrying
about the dot. Positions arrive every few minutes at best, and indoors —
school, sports hall, grandma's basement — the device often cannot get a
good fix at all, so the map keeps showing the last good one with its
honest timestamp.

**No position at all.** Check, in order: location sharing is switched on
in the app; the device is on and charged; the device has coverage. A
device that has been off since morning has nothing to report — and the
map will say so rather than guess.

**The dot is in the wrong place.** Tall buildings and narrow streets
bounce the signal, and live-ish is roughly-where by design — a dot
across the street or a house off is normal. If the dot is plausible and
the timestamp is fresh, the picture is right.

**A check-in was sent but nothing arrived on the phone.** Check the
phone's notification settings for the yoyopod app first — the check-in
itself still lands on the map even when the notification is muted, so
open the app and look before assuming it was never sent.

## Open questions

- Adopt the every-few-minutes cadence as a fixed design — battery and honesty both prefer it — or make the cadence a parent-visible setting?
- Adopt roll-to-Locate-and-hold as the check-in gesture, or hold check-ins back until the one-button grammar is validated with real kids?
- Adopt keep-only-the-latest-fix retention, or keep a few hours of recent fixes so the "no position at all" cases have context?
- Geofence and arrival notifications: explicitly out of V1 “Daylight”, or worth pulling in as the automatic cousin of the check-in?
