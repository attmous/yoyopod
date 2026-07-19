---
title: A Voice Note from the Bus
description: Hold the side button, speak, done — messaging without a screen.
---

*Lina, 11, sends a voice note from the school bus with one held button.*

:::tip[Proposed — the ideal design]
This page is the target design, written out in full so it can be adopted,
adapted, or dropped. Everything on it is proposed — neither implemented
nor committed.
:::

## The moment

It is 3:40 p.m. and the school bus is somewhere between two stops when Lina, 11, remembers: she is going to Merve's house today, not straight home. Around her, half the bus is bent over phones. Lina pulls her yoyopod out of her jacket pocket, turns the wheel to *Mama*, and holds the side button.

"Mama, I'm going to Merve's — back by six."

She lets go. The canvas shows the note is on its way, and the yoyopod goes back in her pocket. The whole thing took less than fifteen seconds, and most of that was deciding what to say.

What Lina doesn't notice — because she doesn't need to — is that the bus is just entering the stretch of road where coverage always drops. The note waits on the device, slips out the moment the signal comes back, and a few minutes later her mother hears Lina's actual voice in the yoyopod app: not a text bubble, her daughter, with the bus rumbling in the background. She records a short reply in the app — "Got it. Say hi to Merve, see you at six" — and on Lina's yoyopod it arrives quietly, an unread note in Talk that plays when Lina chooses to hear it.

## What yoyopod does

Voice notes use the same grammar as everything else on the device: hold the side button, speak, let go — see [using the button](/families/using-the-button/). There is no keyboard, no typing, no autocorrect, and no read receipts to obsess over. The message is the voice itself — tone, background noise, giggle and all.

The recipient comes first, and the recipient is always family. [Talk](/apps/talk/) shows the people on Lina's approved list and only those people; she turns the wheel to one of them and holds. Sending a note to a stranger isn't so much blocked as impossible to express — strangers aren't on the wheel, and the wheel is the only way to choose. The same approved list that governs calls governs notes.

Release means sent. The moment Lina lets go, her part is done: the canvas confirms, the device goes back in the pocket, and the plumbing catches up on its own schedule. Notes are capped at about a minute — a proposed default — which keeps them note-shaped: long enough for a plan change or a "guess what," short enough that nobody records podcasts on the bus.

Replies arrive gently. An incoming note announces itself as an unread item in Talk with a soft cue — it never auto-plays, never interrupts, never demands attention right now. Lina hears it when she decides to. And because these are family messages on a family device, they are visible to parents in the yoyopod app — something the product says plainly to everyone, rather than letting anyone discover it later.

## Behind the scenes

Talk is the face of this moment; the VoIP Engine does the carrying. When Lina releases the button, the device compresses the note and hands it to yoyocloud, which holds it and delivers it to the chosen contact — the yoyopod app on a parent's phone, or another yoyopod in the family — whenever that end is reachable. This is store-and-forward relay, and it is exactly the right shape for a note: neither end has to be online at the same moment, because a voice note exists precisely for the moments a live call can't happen.

The coverage gap on Lina's route is the design working as intended, not surviving in spite of it. Offline, the note queues on the device and uploads when the link returns. If her mother's phone had been the unreachable end instead, yoyocloud would have held the note and delivered it on reconnect. Either way, Lina's experience is "sent" the moment she lets go.

The approved list is enforced on the device itself — inside the VoIP Engine's own send path as well as in the contact-first screens — so it keeps holding even when the network doesn't. The full architecture, including the store-and-forward decision and the proposed limits, lives on the [VoIP Engine](/builders/software/voip-engine/) page; the relay runs on the [cloud backbone](/builders/software/cloud/).

## Why it matters

Lina changed her plans and told her mother herself. That is the independence pillar in miniature: a real message, initiated by the kid, in her own voice, with one motor gesture and zero screen time. She didn't need an account, a keyboard, or anything to look at — she needed a button and something to say.

For her mother, the payoff is just as concrete: she hears Lina — the voice, the mood, the bus in the background — instead of parsing a text bubble for tone. And the scene on the bus makes the whole design philosophy visible in fifteen seconds: one held button, a few honest words, and the device is back in the pocket while the ride goes on. More on how families use this every day is at [Talking](/families/talking/).

## Open questions

- **Recipient flow.** Adopt contact-first as the only way to send — turn the wheel to a person, then hold — or add a default recipient so a hold from anywhere fires off a note to one chosen grown-up? One-gesture speed, against the risk of notes landing with the wrong person.
- **Release-to-send.** Adopt release-to-send as the entire gesture — one motion, and mistakes are cheap among family — or add a replay-and-confirm step before a note leaves the device?
- **Limits.** Adopt the proposed defaults — a roughly 60-second cap per note and a 30-day expiry for undelivered ones — or set different numbers before anything ships?
- **The arrival cue.** Decide how loud an incoming note may be — a glow on the canvas, a soft chime, or both — and adopt never-auto-play as a hard rule rather than a default.
