---
title: Product Definition
description: What yoyopod is, who it serves, and the promise it makes — the first device before a smartphone.
---

yoyopod is a parent-managed **first independent device** for kids ages
7–14, built for the gap *before a smartphone*. It gives kids focused
independence — communication, music, mobility — and gives parents peace
of mind through reliable calling and live-ish location, without a
smartphone's distraction, complexity, and screen addiction.

The positioning line:

> **Safer independence for kids. Peace of mind for parents. Before the
> smartphone.**

## Core definition

| Attribute | Value |
| --- | --- |
| Buyer | parents |
| User | kids ages 7–14 |
| Product type | parent-managed connected companion device |
| Form factor | walkie-talkie-like, tiny screen, minimal input |
| Anti-goal | **not** a smartphone replacement |

## V1 pillars

1. **Whitelist calls and voice messages** — approved contacts only.
2. **Live-ish location** — visibility when it matters. (The hedge is
   deliberate: it is not marketed as real-time tracking.)
3. **Music and audio** — an everyday audio companion.
4. **A parent mobile app** — contacts, settings, and device controls
   stay with the parent.

## The emotional promise

- For the **kid**: independence — a device that feels grown-up and is
  genuinely theirs.
- For the **parent**: safety and peace of mind.

Two trust anchors carry that promise: **reliable reachability** and
**trustworthy location**. Everything else is secondary.

## How the device delivers it

The engineering choices documented across this site all trace back to
this definition: one button and a small canvas
([UI System Guide](/ui/)) because simplicity *is* the product;
whitelisted SIP calling and voice notes
([the switchboard](/runtime/workers/voip/)) because safe communication
is pillar one; cellular + GPS
([the radio room](/runtime/workers/network/)) because reachability and
location are the trust anchors.

:::note[Canonical source]
Condensed from
[`docs/product/PRODUCT_DEFINITION.md`](https://github.com/attmous/yoyopod/blob/main/docs/product/PRODUCT_DEFINITION.md)
— the wording of the positioning line and pillars is deliberate; when in
doubt, quote the canonical document.
:::
