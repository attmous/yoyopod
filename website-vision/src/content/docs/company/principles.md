---
title: Product Principles
description: Screen-light, parent-managed, local-first — the rules features must pass.
---

*The principles every feature decision must pass, stated as testable rules.*

:::caution[Partially filled]
Sections marked *Placeholder* have no as-built content yet; everything else is condensed from the repository (see Sources at the bottom).
:::

## The principles

The canonical one-sentence wording is not frozen yet (see Open
questions), but each principle is already grounded in the documented
product definition and positioning:

| Principle | Where it is documented today |
| --- | --- |
| Parent-managed | Pillar 4: contacts, settings, and device controls stay with the parent — the buyer is the parent, the user is the kid ages 7–14. |
| Screen-light, one-button simplicity | The documented form factor: "walkie-talkie-like, tiny screen, minimal input" — one button and a small canvas, because simplicity *is* the product. |
| Independence, not distraction | Value prop 3: "tiny screen, simple controls, no app rabbit-holes" — and the contrast line "independence without endless distraction". |
| Safe communication first | Pillar 1: whitelist calls and voice messages, approved contacts only. |
| Honest location | Pillar 2 is deliberately hedged as **live-ish** location — visibility when it matters, not marketed as real-time tracking. |

One vision principle — local-first audio that works with no internet —
is not yet stated this way in the canonical product docs; the
documented pillar reads "music and audio — an everyday audio
companion". Freezing that wording is an open question below.

## How we apply them

*Placeholder — no as-built content yet.*

- Every feature proposal answered against all five principles before any design work starts
- Phrasing each principle as a testable question, e.g. "does this still work with no internet?" (exact wording TBD)
- Worked example: how the four on-device screens (Hub, Listen, Talk, Setup) each pass the rules
- Worked example: why hold-as-push-to-talk fits one-button simplicity instead of adding a second button
- Who arbitrates when principles conflict, and how a ruling gets recorded (process TBD)

## What they have already ruled out

The documented anti-goal is explicit: yoyopod is **not** a smartphone
replacement. The anti-positioning list extends it — not a toy, not a
screen-first device, not another addictive kids gadget ("It's a simpler
first step") — and the do-not-say list rules out four marketing
framings outright: *AI for kids* · *a new communication platform* · *a
smart wearable* · *an educational device*. Each of those dilutes the
sharpest truth: it is the first device before a smartphone.

The fuller refusal list lives as a first-class page:
[What yoyopod Is Not](/company/what-we-are-not/).

## Open questions

- TODO: freeze the canonical one-sentence wording of each principle so all pages quote it identically
- TODO: decide whether the principles are ranked when they conflict, or all hard constraints
- TODO: pick the concrete ruled-out examples we are willing to name publicly vs. keep internal

:::note[Sources]
Condensed from
[`docs/product/PRODUCT_DEFINITION.md`](https://github.com/attmous/yoyopod/blob/main/docs/product/PRODUCT_DEFINITION.md)
and
[`docs/product/LANDING_PAGE_POSITIONING.md`](https://github.com/attmous/yoyopod/blob/main/docs/product/LANDING_PAGE_POSITIONING.md)
and the as-built docs site (`website/` in the repository): the Product
Definition and Positioning pages.
:::
