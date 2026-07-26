---
title: "Mia, 8: The Walk to School"
description: First solo walk — location on the parent's phone, one check-in call.
---

*Mia's first solo walk to school, and what her mother Aylin sees from the kitchen.*

:::tip[Proposed — the ideal design]
This page is the target design, written out in full so it can be adopted,
adapted, or dropped. Everything on it is proposed — neither implemented
nor committed.
:::

## The moment

Tuesday morning, Stuttgart. Mia is eight, and today she walks the 900
meters to school by herself for the first time. The deal was made the
night before, at the kitchen table: yoyopod goes with her, and she calls
once from the school gate. That's it. That's the whole arrangement.

The front door clicks shut, and the apartment is suddenly very quiet.
Aylin stays in the kitchen because she promised herself she would. Her
coffee goes cold on the counter next to her phone, and she does not
follow her daughter to the window.

Mia's route is one she has walked a hundred times holding a hand: past
the bakery corner where it smells like pretzels, across the big crossing
with the lights, along the fence, through the school gate. This morning
the route is exactly the same and completely different, because this
morning it is hers.

## What yoyopod does

Aylin picks up her phone once, while the kettle is still warm. In the
yoyopod app, the [Locate](/apps/locate/) view shows a single dot near the
bakery corner, with a small honest line underneath: *updated 3 minutes
ago*. Not a moving blip, not a live feed — a recent fact, plainly dated.
That timestamp is the app being truthful with her: yoyopod's location is
live-ish, a fresh-enough fix every few minutes, and the app never
pretends otherwise. So Aylin checks twice — once at the bakery, once
near the crossing — and not twenty times, because there is nothing on the
screen that invites twenty times. Then she does the dishes.

Mia, meanwhile, is not looking at anything. The canvas on her yoyopod
stays dark and calm in her jacket pocket; nothing buzzes, nothing asks
for her attention. The device's whole job this morning is to be there.

At the school gate she takes it out, turns the wheel to
[Talk](/apps/talk/), and there is Mama — one of the handful of faces her
parents put there, the only faces that exist on the device at all. She
presses the button. In the kitchen, Aylin's phone rings, and it can only
be one person.

The call lasts about thirty seconds. "I'm here." Behind Mia's voice,
Aylin can hear the playground: shrieking, a ball, the bell about to go.
"Okay, Schatz. Have a good day." That's the whole call. It is exactly
enough.

## Behind the scenes

During the walk, Mia's device takes a coarse location fix every few
minutes and publishes it to yoyocloud over its own line home. The
yoyopod app never talks to the device directly — yoyocloud is always in
between — so when Aylin opens the app, it simply asks yoyocloud for the
latest fix and shows it with its timestamp. If a notably fresh fix is
worth a look, a quiet push notification nudges her phone; the app still
goes and fetches it rather than streaming anything. Fixes are kept only
briefly — long enough to be useful this morning, not long enough to
become a diary. The family-facing promise behind all of this is written
up at [Location](/families/location/), and the backend half at the
[cloud backbone](/builders/software/cloud/).

The check-in call is the [VoIP Engine](/builders/software/voip-engine/)
doing its one job well: the Talk wheel shows only whitelisted contacts,
and the call path itself refuses any identity not on the family's list —
two independent layers, both enforced on the device against its
last-synced copy of the whitelist, so the promise holds even in a
coverage gap. Mia could not have called a stranger this morning, and a
stranger could not have called her, and neither fact required anyone to
be careful.

## Why it matters

This is one of the product's pillars made concrete: a live-ish location
plus one reliable call is what turns "maybe next year" into a first solo
walk that actually happens this Tuesday.

For Mia, it is independence with a thread home — a walk that is fully
hers, with one button that reaches her mother if she ever needs it, and
nothing in her pocket competing for her attention along the way.

For Aylin, it is worry converted into something finite: a glance at a
dot, a thirty-second call, done. Not surveillance — the app's honest
timestamp and unhurried cadence are designed to make surveillance
impossible to slide into. The whole positioning of yoyopod fits in this
one scene: safer independence for kids, and peace of mind for the people
who love them. More mornings like this one live at
[Stories](/stories/).

## Open questions

- **The between-fixes view:** adopt the single dot with an honest *updated X minutes ago* line — deliberately no trail, no breadcrumb history — or show a short route trail and accept that it reads more like tracking?
- **Who initiates:** adopt child-initiated calls only for V1 (the yoyopod app's five jobs deliberately do not include a dialer), or let a parent ring the device from the app and accept the scope growth?
- **The absence of alerts:** adopt the deliberate decision that nothing happens when Mia lingers five minutes at the bakery — no geofences, no "stopped moving" alerts — or add movement alerts and accept the anxiety machinery they bring?
- **Fix cadence:** adopt a few-minutes cadence as the walk-friendly balance of freshness against battery and data, or tune the number against real hardware before committing the wording anywhere family-facing?
