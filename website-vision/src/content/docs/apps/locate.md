---
title: "Locate: Location & Check-Ins"
description: Live-ish location awareness for peace of mind.
---

*The location experience — deliberately "live-ish", deliberately not surveillance.*

:::caution[Placeholder]
No as-built content exists for this page yet — the outline below is the target structure.
:::

## What it is

- Live-ish location: parents see roughly where the device is, refreshed often enough for peace of mind
- The hedge is the product: "live-ish" is an honest refresh cadence, never a continuous feed
- The line we draw: reassurance for parents, not minute-by-minute tracking of a child
- The defining scene: [Mia's walk to school](/stories/mia-walk-to-school/)

## Key flows

- Glance check: a parent opens the app and sees a recent-enough position (future)
- Check-in: a kid-initiated "I'm here" moment (shape TBD)
- Arrived-safely reassurance versus continuous tracking — where the feature stops on purpose
- Transparency toward the kid: the device never hides that location is on — [how families see it](/families/location/)

## On the device

- GPS plus the 4G modem provide position fixes
- What, if anything, the glass shows about location state (TBD)
- Battery budget: fix frequency versus battery life trade-off (TBD)
- No kid-facing map or tracking UI — transparency cues only (TBD)

## In the parent app

- Map view with last-known position and a freshness indicator (future)
- Check-in notifications and quiet defaults (TBD)
- Location history: whether any is kept at all, and for how long — see the [privacy stance](/families/privacy/)

## Status today

- GPS and the 4G modem are on the prototype hardware; a network/4G worker runs in the Rust runtime
- Position reporting over the cloud link: staged, not yet wired end to end (TBD)
- The parent-app map experience is future work
- Retention policy for position data: not yet decided (TBD)

## Open questions

- TODO: What refresh cadence earns "live-ish" without draining the battery?
- TODO: Is check-in kid-initiated, arrival-triggered, or both?
- TODO: How much location history, if any, is stored — and where?
- TODO: How is location explained to the kid on the device itself?
