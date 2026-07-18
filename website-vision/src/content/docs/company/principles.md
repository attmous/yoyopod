---
title: Product Principles
description: Screen-light, parent-managed, local-first — the rules features must pass.
---

*The principles every feature decision must pass, stated as testable rules.*

:::caution[Vision stub]
Placeholder in the vision docs — the structure is decided, the content is
not written yet. As-built engineering docs live in the main docs site
(`website/` in the repository).
:::

## The principles

- Screen-light: one small calm glass, no feeds — the screen shows state, it does not demand attention
- Parent-managed: parents decide who can call, what plays, and what the device can do
- Local-first: music and stories work with no internet; the device is useful offline by default
- One-button simplicity: everything a kid does fits tap, double-tap, and hold on a single side button
- Independence-not-distraction: the device exists so a kid can go out alone, not so they stay glued to it

## How we apply them

- Every feature proposal answered against all five principles before any design work starts
- Phrasing each principle as a testable question, e.g. "does this still work with no internet?" (exact wording TBD)
- Worked example: how the four on-device screens (Hub, Listen, Talk, Setup) each pass the rules
- Worked example: why hold-as-push-to-talk fits one-button simplicity instead of adding a second button
- Who arbitrates when principles conflict, and how a ruling gets recorded (process TBD)

## What they have already ruled out

- No camera, no browser, no app store — cut before V1, not deferred
- No feeds or open-ended scrolling surfaces on the glass
- No kid-facing configuration deep enough to bypass parent management
- No feature that only works with a live connection when a local-first version is possible
- Cross-reference the fuller refusal list at [What yoyopod Is Not](/company/what-we-are-not/)

## Open questions

- TODO: freeze the canonical one-sentence wording of each principle so all pages quote it identically
- TODO: decide whether the principles are ranked when they conflict, or all hard constraints
- TODO: pick the concrete ruled-out examples we are willing to name publicly vs. keep internal
