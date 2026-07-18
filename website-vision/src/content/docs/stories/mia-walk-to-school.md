---
title: "Mia, 8: The Walk to School"
description: First solo walk — location on the parent's phone, one check-in call.
---

*Mia's first solo walk to school, and what her mother Aylin sees from the kitchen.*

:::caution[Placeholder]
No as-built content exists for this page yet — the outline below is the target structure.
:::

## The moment

- Tuesday morning, Stuttgart: Mia, 8, walks the 900 meters to school alone for the first time
- Aylin stays behind in the kitchen — nervous, coffee going cold, phone on the counter
- The deal they made the night before: yoyopod on, one check-in call from the school gate
- Scene beat: the front door closes, and the silence in the apartment is louder than usual
- Scene beat: Mia's route — the bakery corner, the crossing with the lights, the school gate

## What yoyopod does

- Aylin opens the parent app and sees Mia's live-ish location move along the route (parent app is future work — this is the target experience)
- No live tracking obsession by design: the location is live-ish, not a real-time surveillance feed — beat: Aylin checks twice, not twenty times
- At the gate, Mia holds the side button and check-in call rings only Aylin — whitelist means nobody else could be on the line
- The call is short: "I'm here." Beat: Aylin hears the playground noise in the background
- What Mia's screen shows during the walk: the calm Hub wheel, nothing demanding her attention

## Behind the scenes

- How a location fix travels from the device's GPS and 4G modem to the parent's phone — see [Locate](/apps/locate/)
- How the check-in call is placed and why only whitelisted contacts can ring — see [Talk](/apps/talk/)
- Which runtime workers are awake during a walk (network/4G, cloud link, voip) — see [the runtime](/builders/software/runtime/)
- Update cadence and battery trade-off behind "live-ish" (exact cadence TBD)

## Why it matters

- The pillar made concrete: live-ish location plus one call equals a first solo walk that actually happens
- For Mia: independence without a smartphone in her pocket
- For Aylin: worry converted into a glance and a thirty-second call
- The positioning in one scene: safer independence for kids, peace of mind for parents

## Open questions

- TODO: What exactly does Aylin see between location fixes — a dot, a trail, a "last seen" timestamp?
- TODO: Does Mia initiate the check-in call, or can Aylin also ring the device from the app? (TBD)
- TODO: What happens in the story if Mia stops moving for five minutes — do we show an alert concept, or deliberately not?
- TODO: How do we write the "twice, not twenty times" beat without implying features (geofences, notifications) that are undecided?
