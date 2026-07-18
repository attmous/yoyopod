---
title: Roadmap
description: "The rounds: where V1 stands and what comes after."
---

*The honest trajectory: V1 pillars first, everything else after.*

## Where V1 stands

The roadmap is kept as the project's **honesty doc**: what is broken
today, what works, and when it gets fixed. Its current subject is the
**Rust CLI rebuild** — the old Python operator CLI (~21k lines) was
deleted in one move, and a new Rust CLI is being rebuilt at `cli/` in
business-need-sized rounds. Each round restores a capability shaped for
current reality rather than porting assumptions that no longer hold.

The rounds ledger (as of 2026-07-12):

| Round | Scope | State |
| --- | --- | --- |
| 0 | Demolition + scaffolding | ✅ merged |
| 1 | Daily dev loop (`yoyopod target …` Rust MVP) | ✅ merged |
| 2 | Restore hardware validation (`yoyopod target validate`) | 🔄 in progress |
| 3 | Restore prod release pipeline | ⏳ not started |
| 4+ | Diagnostics (`pi voip/power/network/rust-ui-host`) | ⏳ not started |

What works today: the Rust dev runtime on the device (no Python
anywhere in the path), the prod runtime on already-shipped slots, CI's
per-commit ARM64 artifact, and the Round-1 CLI — with `target deploy`
as the centerpiece (push → find the CI artifact for the exact commit →
sync the Pi → install binaries → restart → verify).

What is broken today, stated plainly:

- **Prod slot builds are paused** — the release CI jobs are disabled;
  no new release tarballs until Round 3 lands.
- **Diagnostics are gone** with the Python CLI — SSH manually until
  Round 4+.
- **VoIP and cloud-voice validation stages are stubs** (exit 2) until
  the Round-2 follow-up ports them.

## Next

Round 2 is in flight (started 2026-07-12): hardware validation returns
as `yoyopod target validate`, with the validation stages living in a
new on-Pi companion binary (`yoyopod-on-pi`) rather than driving SSH
from the dev machine. That architecture was chosen because the stages
supervise worker binaries over a long-lived process, the validator
consumes the shared protocol crate so it cannot drift from what the
workers speak, and CI ships it in the same per-commit bundle so
validation always matches the deployed commit. The base stages
(deploy, smoke, stability, navigation, lvgl) come first; the follow-up
ports the VoIP stage (SIP registration + call soak) and the
cloud-voice stage (STT/TTS worker boundary checks).

Round 3 then restores the prod release pipeline: release manifest,
slot contract, slot tarball builder, and health preflight ported to
Rust, and the disabled CI release jobs re-enabled. Until it lands,
shipping a prod release is simply not possible — release windows are
planned around the rebuild.

## Later

Round 4+ restores diagnostics (`pi voip`, `pi power`, `pi network`,
`pi rust-ui-host`) on a business-need basis — each gap that proves
painful enough to fix becomes its own small round, and diagnostics can
join the same on-Pi binary the validator lives in. The rounds carry
ordering and status flags, not dates.

On the hardware side, "later" is **V1 “Daylight”** — the designed PCB that
replaces today's V0 “Dawn” off-the-shelf rig once its exit criteria are
defined; see [From Prototype to Product](/builders/hardware/roadmap/).

## Open questions

- TODO: confirm the current staged status of calling and the real status of the location pillar
- TODO: decide whether this public page shows timeframes at all, or only ordering
- TODO: define the exit criteria that let us call V0 “Dawn” done and commit to the V1 “Daylight” board

:::note[Sources]
Condensed from
[`docs/ROADMAP.md`](https://github.com/attmous/yoyopod/blob/main/docs/ROADMAP.md)
and the as-built docs site (`website/` in the repository): the Roadmap
page.
:::
