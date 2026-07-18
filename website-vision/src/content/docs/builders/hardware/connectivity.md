---
title: "Connectivity: 4G & GPS"
description: The modem, the SIM, and location hardware.
---

*The 4G modem, SIM provisioning, and GPS — the hardware behind Locate and Talk.*

:::caution[Vision stub]
Placeholder in the vision docs — the structure is decided, the content is
not written yet. As-built engineering docs live in the main docs site
(`website/` in the repository).
:::

## Overview

- What connectivity is for: whitelist calls, voice messages, live-ish location, and the cloud link — nothing else
- Why the device still works offline: local-first music and stories do not depend on the modem
- The honesty rule for location: GPS gives live-ish position, and we never call it real-time
- Radios in scope: 4G + GPS; any other radio's role is undecided (TBD)

## Key components

- 4G modem: SIM7600 family in the prototype; product modem selection (TBD)
- SIM: physical SIM vs. eSIM, and how a family gets a provisioned SIM in the box (TBD)
- GPS receiver and antenna path (shared with or separate from the modem — prototype uses the modem's GPS; product TBD)
- Antenna design and placement in a small kid-carried enclosure (TBD)

## Interfaces & contracts

- The network worker: the Rust runtime process that owns the 4G modem and connection state
- The cloud worker: MQTT link to the backend riding on the modem's data connection — see [Cloud](/builders/software/cloud/)
- How GPS fixes flow from hardware to the Locate experience — see [Locate](/apps/locate/)
- The contract a different product modem must satisfy (AT/QMI surface, GPS access, power states) so workers survive the swap (TBD)

## Today vs. target

- Today: SIM7600-family modem on the prototype path, supervised by the network worker
- Target: product-board modem and antenna design chosen for cost, power draw, and regional band coverage (TBD)
- Fixed by intent: 4G + GPS serve Talk and Locate only; there is no browser or app store to feed
- Open: carrier/MVNO strategy, roaming behavior, and modem power management for battery life (TBD)

## Open questions

- TODO: Physical SIM or eSIM — and who provisions it, the family or us as part of the product?
- TODO: Which regional 4G band sets must the product modem cover for the launch markets?
- TODO: What is the modem's power budget, and how aggressively can it sleep without missing incoming calls?
- TODO: Does the product keep using modem-integrated GPS, or move to a dedicated receiver?
