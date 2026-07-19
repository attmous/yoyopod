---
title: Grandma Calls at Six
description: "The whitelist in action: only family gets through."
---

*Emil, 7, gets his daily call from Grandma — and a stranger's number never rings.*

:::tip[Proposed — the ideal design]
This page is the target design, written out in full so it can be adopted,
adapted, or dropped. Everything on it is proposed — neither implemented
nor committed.
:::

## The moment

Six o'clock, every evening. Grandma calls Emil from two towns away, and
it is the fixed point of his day — more reliable than dinner, which
sometimes runs late, and homework, which sometimes doesn't happen.

At 18:01 the yoyopod on the kitchen shelf chimes gently and the canvas
lights up with Grandma's face. Emil, seven, drops his pencil, grabs the
device, and presses the button. "Omaaa." Then the call itself, which is
about nothing and therefore about everything: the maths homework, the
neighbor's dog who got into the Weissmanns' garden again, what's for
dinner on both ends of the line.

Here is the part of the story nobody in the kitchen noticed. Earlier
that afternoon, an unknown number tried to reach Emil's device. On
Emil's end, nothing happened. No ring, no blink, no badge, no missed
call to wonder about. The afternoon simply continued.

Emil's parents have never sat him down for the talk about not answering
strangers. There is nothing to explain, because there is nothing to
answer.

## What yoyopod does

On yoyopod, only the people a parent has approved can reach the device —
and everyone else does not get declined, or silenced, or sent to a
voicemail. They simply never ring. From where Emil sits, callers other
than family do not exist.

Answering, for a seven-year-old, is one glance and one press: the canvas
says Grandma, the button says answer, and there are no other decisions
in the room. The unknown caller from the afternoon left nothing behind
on Emil's side — no missed-call anxiety, no red dot demanding to be
cleared, no choice a child has to get right. And calling out works the
same way in reverse: Emil's [Talk](/apps/talk/) wheel shows Grandma,
Mama, Papa, and his uncle in Hamburg — the family's approved people, and
only them. Dialing a stranger isn't forbidden on this device; it is
unexpressible. There is no dial pad to forbid.

Grandma's side is the best part: there is no Grandma side. She calls
from her own phone, the way she has called everyone for fifty years — no
app to install, no account to create, nothing to charge or update. She
was set up once, by Emil's parents, and has been six o'clock ever since.
(One honesty note: this scene narrates the plain-phone-number option for
whitelist contacts — whether V1 supports it, or keeps calling between
yoyopods and the yoyopod app only, is an open decision on
[Talking](/families/talking/).)

## Behind the scenes

The list of approved people — the whitelist — lives authoritatively in
yoyocloud and is edited in exactly one place:
[the yoyopod app](/apps/parent-app/), behind a parent's account (see
[Parental controls](/families/parental-controls/)). yoyocloud syncs a
copy down to Emil's device, and the app tells parents the truth about
where an edit stands: *saved* when yoyocloud has it, *active on device*
once Emil's yoyopod has confirmed the update.

On the device, the [VoIP Engine](/builders/software/voip-engine/)
enforces the list at two independent layers. The call path itself
refuses any identity not on the list — inbound calls from strangers are
rejected before the device ever rings, which is why Emil's afternoon
contained nothing at all. And the Talk wheel renders only whitelisted
contacts, so the interface cannot even express a call to anyone else.
Two layers, so that one bug is never the distance between a stranger and
a child.

Enforcement always runs against the device's last-synced copy, so a
dead network never loosens anything: offline, Emil's device enforces
exactly the list it last confirmed. And a device that has never synced a
list enforces the empty one — closed until family exists. Stale is never
open.

## Why it matters

The whitelist is not a filter Emil manages, or a setting he could get
wrong. It is a world with only family in it, built before he ever
pressed a button.

For Emil, it means a daily ritual with his grandmother — hers and his,
at six, reliably — on a device that asks nothing else of him.

For his parents, the entire category of "who can contact my child" was
settled once, at setup, in the app — and stays settled without vigilance,
because the device holds the line even when nobody is watching it.

And for Grandma, it means being a first-class part of the product
without ever touching it. She thinks of it as calling Emil. She is
right. That is the whole design. More evenings like this one live at
[Stories](/stories/).

## Open questions

- **Refused-call visibility:** adopt silent-drop as the complete story — nothing shown to Emil *and* nothing logged for parents — or give parents a quiet record of refused attempts in the app, and accept that the record itself invites worry?
- **How Grandma gets on the list:** adopt parent-entered contacts as the only path (a parent types Grandma's number into the app), or add an invite flow Grandma confirms from her own phone, trading simplicity for verified numbers?
- **Missed calls within the family:** adopt a gentle mark on Grandma's face on the Talk wheel with one-press callback when Emil misses six o'clock, or no missed-call surface at all — and is that calm or confusing for a seven-year-old?
- **Quiet hours:** adopt parent-set quiet hours for when the device rings audibly, or always ring for whitelisted family on the argument that the whitelist itself is the filter?
