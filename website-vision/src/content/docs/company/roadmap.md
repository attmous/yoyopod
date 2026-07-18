---
title: Roadmap
description: "The rounds: where V1 stands and what comes after."
---

*The honest trajectory: V1 pillars first, everything else after.*

:::caution[Vision stub]
Placeholder in the vision docs — the structure is decided, the content is
not written yet. As-built engineering docs live in the main docs site
(`website/` in the repository).
:::

## Where V1 stands

- Local-first music/audio: playback works on-device today (Rust runtime, media worker via mpv)
- Whitelist calls & voice messages: staged — the voip worker exists, end-to-end calling not yet complete
- Live-ish location: hardware in place (4G modem + GPS), pillar status TBD
- Parent mobile app: future work — planned apps/ directory, nothing shipped yet
- Prototype hardware carries all of this: Raspberry Pi Zero 2W + PiSugar Whisplay HAT, explicitly a prototype path

## Next

- Finish the four V1 pillars before anything new — the gate for calling it V1
- Parent app from planned to real: pairing, whitelist management, location view
- Product board evaluation: a board with its own display may replace the prototype path (TBD)
- Hardening the runtime and workers for daily-driver use by real families
- Sequencing and rough timeframes for the above (TBD — deliberately not dated here)

## Later

- Everything beyond the V1 pillars lives in one place: [What Comes Next](/apps/future/)
- SDK packages (planned packages/ directory) — future work, scope undecided
- How "later" ideas get admitted: they must pass the [Product Principles](/company/principles/) and never cross [What yoyopod Is Not](/company/what-we-are-not/)
- What we will not put on any roadmap, ever — see [What yoyopod Is Not](/company/what-we-are-not/)

## Open questions

- TODO: confirm the current staged status of calling and the real status of the location pillar
- TODO: decide whether this public page shows timeframes at all, or only ordering
- TODO: define the exit criteria that let us call the prototype path done and commit to a product board
