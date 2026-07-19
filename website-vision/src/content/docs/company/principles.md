---
title: Product Principles
description: Screen-light, parent-managed, local-first — the rules features must pass.
---

*The principles every feature decision must pass, stated as testable rules.*

:::tip[Proposed — the ideal design]
This page mixes as-built fact (covered by the Sources note) with the target
design, written out in full so it can be adopted, adapted, or dropped.
Everything marked *Proposed* is neither implemented nor committed.
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

*Proposed — the ideal design, not yet adopted.*

Every feature proposal answers the principles before any design work
starts — not as a mood check but as a short list of questions, each
with a yes-or-no answer. The proposed working form of each principle
is one testable question:

- **Parent-managed:** can the parent see it, change it, or turn it off
  from the yoyopod app? A feature that creates state a parent cannot
  reach fails, whatever else it does well.
- **Screen-light, one-button simplicity:** does this make a kid look
  at the canvas longer, or add a second way to press? The canvas is a
  glance, not a destination, and the button is the whole input story.
- **Independence, not distraction:** does this help a kid walk out the
  door, or pull them back to the device? A good yoyopod moment ends on
  purpose — the song finishes, the call finishes, the kid moves on.
- **Safe communication first:** can anyone outside the whitelist reach
  the child through this — in any state, including offline? If the
  answer is ever yes, the feature does not ship until it is no.
- **Honest location:** could a parent read this wording as real-time
  tracking? Location is live-ish — periodic and coarse — and every
  sentence we write about it has to survive that adjective.
- **Local-first:** does this still work with no internet? Music and
  stories live on the device, so a dead café Wi-Fi should never
  silence a bedtime story.

One further question is proposed not as an ordinary principle but as a
recorded, permanent commitment, carried over from the Speech Engine's
design: **push-to-talk only, forever.** Does the microphone open any
way other than the [held button](/families/using-the-button/)? No wake
word, no always-listening — not as an experiment, not in any version.
Writing it here is deliberate: a commitment recorded in the principles
is one that no future planning meeting has to re-litigate.

**Worked example — four screens, one test.** The Hub is a wheel of
destinations: spin, see a name, hear it spoken, pick. Nothing scrolls,
nothing notifies, nothing asks to be checked — a glance passes
screen-light, and its stillness passes independence.
[Listen](/apps/listen/) plays what a parent loaded, with no internet
required — local-first by construction, parent-managed by definition —
and the canvas shows what is playing, then rests.
[Talk](/apps/talk/) is contact-first: the kid sees the names the
parent approved and nothing else, and because the whitelist is
enforced on the device itself, safe communication holds even offline.
[Setup](/apps/setup/) shows a short code on the canvas and lets the
yoyopod app do everything else — the device never grows a settings
maze, which is parent-managed doing its quiet work. Four screens, all
the questions, no exceptions needed: that is what the principles look
like when they hold.

**Worked example — the hold, not a second button.** When
[talking](/families/talking/) was designed, the obvious move was a
dedicated talk key — walkie-talkies have one, and it would have been
easy. Holding the one button won instead, because it passes the tests
the extra key would fail. One button means one thing to learn:
screen-light, one-button simplicity in its purest form. The hold makes
speaking a deliberate physical act — the microphone is open exactly as
long as a small thumb says so, which is the same fact the
[privacy promise](/families/privacy/) rests on. And the refusal
matters beyond this one choice: a second button is never just a second
button; it is the precedent for a third.

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

- **Adopt the testable-question wording** above as the frozen canonical
  form of each principle, quoted identically on every page — or keep
  the wording loose and accept drift between pages.
- **Adopt "push-to-talk only, forever" as a recorded principle**,
  closing the wake-word question permanently as the Speech Engine
  design proposes — or leave it a design decision a future version
  could reopen.
- **Promote local-first to a named principle** ("does this still work
  with no internet?") — or keep it folded into the documented audio
  pillar as it stands today.
- **Decide arbitration:** whether the principles are ranked when they
  conflict or are all hard constraints, who records a ruling when a
  feature is refused — and, at the same time, which ruled-out examples
  we name publicly versus keep internal.

:::note[Sources]
Condensed from
[`docs/product/PRODUCT_DEFINITION.md`](https://github.com/attmous/yoyopod/blob/main/docs/product/PRODUCT_DEFINITION.md)
and
[`docs/product/LANDING_PAGE_POSITIONING.md`](https://github.com/attmous/yoyopod/blob/main/docs/product/LANDING_PAGE_POSITIONING.md)
and the as-built docs site (`website/` in the repository): the Product
Definition and Positioning pages.
:::
