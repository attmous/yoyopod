---
title: Security Model
description: Identity, whitelisting, transport, and updates.
---

*The security posture a parent-managed kids device must be able to defend.*

:::caution[Vision stub]
Placeholder in the vision docs — the structure is decided, the content is
not written yet. As-built engineering docs live in the main docs site
(`website/` in the repository).
:::

## Overview

- The threat framing: a device carried by a kid, managed by a parent, reachable over 4G
- The four pillars this page will cover: whitelist enforcement, device identity, transport security, the update path
- What the hardware refuses to have, by design: no camera, no browser, no app store
- Mostly target-state: the posture is decided in outline, the mechanisms are not

## Key components

- Whitelist enforcement: only parent-approved contacts can call or leave voice messages (enforcement point TBD)
- Device identity: each device provably itself to the cloud (mechanism TBD)
- Transport security: protecting the MQTT line home (detail TBD)
- The update path: how updates reach the device safely (mechanism TBD)

## Interfaces & contracts

- What the parent app may change, and what it may never see (TBD)
- Location data handling: live-ish reporting and retention (TBD) — family-facing view at [Privacy](/families/privacy/)
- What a compromised cloud can and cannot do to a device — a target property to state and defend (TBD)
- The push-to-talk data path: what leaves the device and when (TBD)

## Today vs. target

- Explicitly target-state: implementation status belongs to the as-built engineering docs (`website/` in the repository)
- Today: the MQTT link and provisioning exist; the hardened posture described here is the target
- Target: every pillar written down with its enforcement point and its audit story
- Prototype hardware vs. product board differences in the security story (TBD)

## Open questions

- TODO: where is the whitelist authoritatively enforced — device, cloud, or both?
- TODO: what does the update chain look like on the prototype path vs. a product board?
- TODO: what location retention policy do we commit to publicly?
