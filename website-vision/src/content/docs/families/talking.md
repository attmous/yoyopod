---
title: "Talking: Calls & Voice Notes"
description: Whitelist calls and quick voice messages to approved contacts.
---

*How a kid calls family and sends voice notes — and why only the whitelist gets through.*

:::caution[Partially filled]
Sections marked *Placeholder* have no as-built content yet; everything else is condensed from the repository (see Sources at the bottom).
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

*Placeholder — no as-built content yet.*

- Turn the wheel to [Talk](/apps/talk/) from the Hub
- Picking a contact from the whitelist on the glass
- Making a call: how it starts, sounds, and ends (exact flow TBD)
- Sending a voice note: hold the button, speak, release — push-to-talk
- Receiving: what an incoming call or voice note looks and sounds like (TBD)
- Two worked examples: [Grandma calls](/stories/grandma-calls/) and [a voice note from the bus](/stories/voice-note-from-the-bus/)

## Tips

*Placeholder — no as-built content yet.*

- Only the whitelist gets through — unknown numbers never reach the device, in either direction
- Practice push-to-talk like a walkie-talkie before the first real errand
- Keep the whitelist short and familiar: family first
- Voice notes beat calls for quick "I'm here" moments

## Troubleshooting

*Placeholder — no as-built content yet.*

- A call won't connect — coverage, whitelist, and device-state checks
- Voice note recorded but not delivered (retry behavior TBD)
- A relative says they can't reach the device — they're probably not on the whitelist
- The other side can't hear well — microphone and speaker basics

## Open questions

- TODO: What exactly does an incoming call look like on the glass, and can a kid decline?
- TODO: Do voice notes queue and retry when coverage drops mid-send?
- TODO: Can whitelisted contacts use a plain phone, or do they need the parent app?
- TODO: Is there any call-length or quiet-hours limit on Talk (parent-set)?

:::note[Sources]
Condensed from
[`docs/product/PRODUCT_DEFINITION.md`](https://github.com/attmous/yoyopod/blob/main/docs/product/PRODUCT_DEFINITION.md)
and
[`docs/ROADMAP.md`](https://github.com/attmous/yoyopod/blob/main/docs/ROADMAP.md)
and the as-built docs site (website/ in the repository): the Product
Definition and Roadmap pages and the UI guide's navigation page (Screens
& Navigation).
:::
