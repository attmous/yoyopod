---
title: From Prototype to Product
description: "Hardware V0 “Dawn” today — off-the-shelf boards wired together; V1 “Daylight” is the designed PCB."
---

*The honest hardware trajectory: V0 “Dawn” today, V1 “Daylight” ahead.*

:::tip[Proposed — the ideal design]
This page mixes as-built fact (covered by the Sources note) with the target
design, written out in full so it can be adopted, adapted, or dropped.
Everything marked *Proposed* is neither implemented nor committed.
:::

## Overview

The hardware generations carry names from the brand's Sunrise & Midnight
story:

| Generation | What it is |
| --- | --- |
| **V0 “Dawn”** — today | The prototype rig: boards and kits **available on the market, wired together** to realize the kid's device fast. The Raspberry Pi Zero 2W, the Whisplay HAT, the PiSugar 3, and the SIM7600 modem were picked because they are **off the shelf** — chosen for speed of prototyping, not designed for this product. |
| **V1 “Daylight”** — next | The **designed PCB**: components picked per the product design and soldered onto one purpose-built board — its own display, audio, power, and modem choices. V1 matures through the industry build stages: **EVT** (engineering validation — does the board work), **DVT** (design validation — does the *product* work, enclosure and all), **PVT** (production validation — can the line build it at quality). |

V0 is explicitly a **prototype path, not a permanent promise**. What stays
constant across the V0 → V1 transition is set by intent, not by the
prototype: one button, a small calm screen, speaker + microphone, 4G + GPS,
no camera.

The project keeps a living **honesty doc** — the roadmap — that tracks
what works, what is broken, and when it gets fixed. Its current subject is
the staged Rust rebuild of the operator tooling around the hardware, done
in business-need-sized rounds rather than a line-by-line port, because a
port would rebuild assumptions that no longer hold.

## Key components

*Proposed — the ideal design, not yet adopted.*

V0 “Dawn” chose components for one criterion: **available today**. V1
“Daylight” gets to choose properly, and the same four questions are asked
of every subsystem: what does it cost at target volume, what does it draw
from the battery, does mainline Linux support it (drivers that outlive a
vendor's interest, not a frozen vendor kernel), and — where radio or
audio is involved — does it cover the bands and ship the codecs the
product needs.

**Compute.** The selection criteria, in order: idle power draw (a carried
device lives at idle, so idle *is* the battery budget), mainline kernel
support for the SoC, unit cost, and a supplier longevity commitment
measured in years rather than roadmap slides. The Pi Zero 2W has proven
the performance class is sufficient; V1 does not need more compute, it
needs the same compute with a power story and a supply story.

| Option | What it looks like | Trade-off |
| --- | --- | --- |
| Full custom, SoC board-down | SoC, RAM, and PMIC laid out directly on our board | the lowest unit cost at real volume, but the hardest EVT: DDR routing, power sequencing, and thermals are all ours to get wrong |
| **Compute-module family** | a proven system-on-module carrying SoC + RAM + PMIC, mounted on our carrier board | **Recommended** — the carrier board holds everything product-specific (audio, power, modem, antennas) while the module vendor carries the hard layout and the longevity commitment; the V0 runtime ports fastest, and a later module swap does not respin the carrier |
| Stay on a Pi-class SBC | keep a single-board computer inside a product enclosure | not a product path: wrong form factor, no supply commitment, and the HAT stack-up cannot meet the enclosure |

**Display.** The canvas stays what it is by intent — small, portrait,
calm. Criteria: a panel with a mainline driver or one the existing
userspace SPI path can drive, readability indoors and out, cost, and
power. Nothing about V1 argues for a bigger screen; a bigger screen is on
the [list of things we refuse](/company/what-we-are-not/). Deep dive:
[The Canvas: Display & Input](/builders/hardware/display/).

**Audio.** The most constrained choice on the board: a codec with a solid
mainline ASoC driver (the WM8960 earned its V0 place exactly there), a
speaker that reaches kid-safe loudness inside a closed enclosure, and a
microphone placed for push-to-talk at arm's length. Codec availability is
a real criterion — the part must stay buyable for the product's whole
life, not just through EVT. Deep dive:
[Audio Path](/builders/hardware/audio/).

**Power.** A battery sized to a full day of real kid use with margin, a
charger and fuel-gauge pair with mainline drivers, and the two features
the PiSugar proved indispensable carried onto the board proper: a
hardware watchdog and an RTC. Deep dive:
[Power & Battery](/builders/hardware/power/).

**Connectivity.** The modem is selected against the written contract on
the [connectivity page](/builders/hardware/connectivity/): band coverage
for the launch markets, paging-aware sleep, on-demand GNSS, and
distinguishable fault classes. The SIM becomes a design decision there
(soldered eSIM is the recommendation), and the antennas are placed before
the rest of the layout, not after.

**Enclosure and industrial design.** From bare rig to a shell a kid
carries daily: stated and tested drop targets, RF-transparent material
where the antennas live, no small removable parts, and a shape that
survives a school bag. The enclosure and the board are designed together
— antenna keep-outs, speaker porting, and button feel are board inputs —
which is exactly why DVT validates the product, not just the PCB.

## Interfaces & contracts

*Proposed — the ideal design, not yet adopted.*

The software bet that makes the V0 → V1 swap survivable is already
placed: every hardware subsystem sits behind exactly one worker process
under [The yoyocore Runtime](/builders/software/runtime/), so a board
change lands in drivers and worker configuration — never in feature code.
Five contracts must hold across the swap: **button events**, the
**canvas** the [UI Engine](/builders/software/ui/) draws to, **audio in
and out**, **modem and GPS access**, and **power telemetry**. Per-board
wiring detail stays where it belongs, in the as-built engineering docs
(`website/` in the repository).

**The EVT bring-up checklist.** EVT asks "does the board work" — and for
yoyopod that question has an exact form: *does the unchanged runtime
exercise every engine contract on the candidate board?* The checklist, in
bring-up order:

1. **Boot and slots** — the signed yoyoOS image boots from either A/B
   slot, and a deliberately failed health check rolls back cleanly
   ([Security Model](/builders/software/security/)).
2. **Button events** — press, hold, and release arrive through the input
   path with the same semantics the whole interface is built on; the one
   physical control is the one contract with zero tolerance for drift.
3. **The canvas** — the [UI Engine](/builders/software/ui/) drives the
   panel at full frame rate in portrait, through whatever display path
   the board provides.
4. **Audio out** — the [Media Engine](/builders/software/media-engine/)
   plays local files through the new codec, respecting loudness limits.
5. **Audio in and duplex** — push-to-talk capture reaches the
   [Speech Engine](/builders/software/speech-engine/), and the
   [VoIP Engine](/builders/software/voip-engine/) completes a
   full-duplex call in both directions on the new audio path.
6. **Modem and GPS** — the network worker walks its state machine from
   `Off` to `Online` on the new modem, and a GNSS fix is queried and
   normalized, per the [modem contract](/builders/hardware/connectivity/).
7. **Power telemetry** — battery state of charge and charging status read
   correctly, the hardware watchdog is fed, and the RTC keeps time
   through a power-off.

The pass criterion matters as much as the list: a candidate board passes
EVT only if **nothing above the workers changed**. If a feature crate
needed an edit to turn a checklist item green, a hardware assumption
leaked through a contract — and that leak is fixed before DVT, because
DVT validates the product and cannot afford to also be debugging the
abstraction.

## Today vs. target

Today, everything runs on the V0 “Dawn” rig, and that path stays the
reference while it earns its keep. Where the rebuild rounds stand (as of
2026-07-12):

| Round | Scope | State |
| --- | --- | --- |
| 0 | Demolition + scaffolding | merged |
| 1 | Daily dev loop (deploy, status, logs against the device) | merged |
| 2 | Restore **hardware validation** on the device | in progress |
| 3 | Restore the prod release pipeline | not started |
| 4+ | Diagnostics (voip / power / network / UI host) | not started |

Carried honestly from the as-built roadmap: prod slot builds are disabled
(no new release tarballs until Round 3 lands), on-device diagnostics are
gone until Round 4+ (SSH manually until then), and two validation stages
(voip, cloud-voice) are stubs pending the Round 2 follow-up. The target
remains V1 “Daylight”: a purpose-built board in a kid-proof enclosure
running the same Rust runtime and UI, earned through EVT → DVT → PVT.
What we will not do: chase hardware features — camera, bigger screen, app
store — that break the "before the smartphone" position. The explicit
decision gates for starting V1 are not yet defined (see the open questions
below).

## Open questions

- **Decision gates:** adopt concrete V1 triggers — a stated demand signal in units, a unit-cost target, and a season of V0 battery and reliability data — or allow V1 “Daylight” to start on conviction alone?
- **Compute path:** adopt the compute-module recommendation above, or commit to a full board-down design and accept the harder EVT for the lower unit cost?
- **V0 afterlife:** keep the Pi + HAT rig alive as the community and development target after V1 ships, or freeze it once V1 passes EVT?
- **Certification timing:** treat CE/FCC and children's-product safety testing as EVT-stage design inputs, or defer them to DVT and accept the risk of a respin?

:::note[Sources]
Condensed from
[`docs/ROADMAP.md`](https://github.com/attmous/yoyopod/blob/main/docs/ROADMAP.md)
and the as-built docs site (`website/` in the repository): the product
Roadmap page.
:::
