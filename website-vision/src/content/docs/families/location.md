---
title: Location & Check-Ins
description: Live-ish location for peace of mind — what it is and isn't.
---

*What parents see on the map, how fresh it is, and what a check-in means.*

:::caution[Vision stub]
Placeholder in the vision docs — the structure is decided, the content is
not written yet. As-built engineering docs live in the main docs site
(`website/` in the repository).
:::

## What you'll need

- A paired device with location sharing enabled by a parent
- The parent app, where the map lives
- Mobile coverage and GPS signal on the kid's route

## Steps

- Opening the map in the parent app: one kid, one dot, a freshness timestamp
- Reading "live-ish": how fresh the position is and why it isn't second-by-second
- What a check-in is and how a kid triggers one (gesture and flow TBD)
- What parents get when a check-in arrives (notification shape TBD)
- A worked example: [Mia's walk to school](/stories/mia-walk-to-school/)

## Tips

- The map is live-ish, not real-time tracking — expect minutes of freshness, not seconds (exact cadence TBD)
- Talk about the map with the kid: they should know what parents can see
- Trust the timestamp more than the dot — an old position is old information
- Location and privacy go together: see [Our Privacy Promise](/families/privacy/)

## Troubleshooting

- The dot hasn't moved in a while — coverage gaps, indoor GPS, and update cadence
- No position at all — is location sharing on, is the device on and in coverage?
- The dot is in the wrong place — GPS accuracy in cities and buildings
- Check-in pressed but nothing arrived on the phone (TBD)

## Open questions

- TODO: Actual update cadence and how it trades off against battery life
- TODO: How is a check-in triggered on a one-button device — which gesture, from which screen?
- TODO: Are there geofence or arrival notifications in V1, or is that later? (TBD)
- TODO: How is location history handled — shown, retained, or not kept at all?
