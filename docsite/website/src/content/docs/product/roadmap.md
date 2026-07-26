---
title: Roadmap
description: The honesty doc — the staged Rust CLI rebuild, what works today, what is broken, and when it comes back.
---

The roadmap is the project's **honesty doc**: what is broken today, what
works, and when it gets fixed. It tracks the **Rust CLI rebuild** — the
old Python operator CLI (~21k lines) was deleted in one move, and a new
Rust CLI is being rebuilt at `cli/` in business-need-sized rounds.

## Round status (as of 2026-07-12)

| Round | Scope | State |
| --- | --- | --- |
| 0 | Demolition + scaffolding | ✅ merged |
| 1 | Daily dev loop (`yoyopod target …` Rust MVP) | ✅ merged |
| 2 | Restore hardware validation (`yoyopod target validate`) | 🔄 in progress |
| 3 | Restore prod release pipeline | ⏳ not started |
| 4+ | Diagnostics (`pi voip/power/network/rust-ui-host`) | ⏳ not started |

Why rounds instead of a port: the runtime went Rust-only, so a
line-by-line port would rebuild dead assumptions (e.g. `target sync` as
`git pull + restart`, valid only when source files *were* the
executable). Each round restores a capability shaped for current reality.

## What works today

- The dev runtime: `yoyopod-dev.service` execs
  `device/runtime/build/yoyopod-runtime` directly — no Python anywhere.
- CI's `rust-device-arm64` job producing the
  `yoyopod-rust-device-arm64-<sha>` artifact.
- The Round-1 CLI: `target config edit`, `target mode
  {status, activate}`, **`target deploy`** (the centerpiece: push → find
  the CI artifact for the exact commit → sync the Pi → install binaries →
  restart → verify), `target {status, restart, logs, screenshot}`.
- All Rust workspace commands (`cargo check/build/test`).

## What is broken today

- **Prod slot builds** — CI `slot-arm64` and `release.yml` are disabled;
  no new release tarballs until Round 3.
- **Diagnostics** (`pi voip/power/network/rust-ui-host`) — gone with the
  Python CLI; SSH manually until Round 4+.
- **VoIP + cloud-voice validation stages** — `yoyopod-on-pi validate
  {voip, cloud-voice}` are stubs (exit 2), the Round-2 follow-up.

## Workarounds during the gap

| Need | Do this instead |
| --- | --- |
| Validate a Rust change on hardware | `yoyopod target deploy`, then SSH: `journalctl -u yoyopod-dev.service -f` |
| Ship a prod release | **You can't.** Plan release windows around the rebuild. |
| Read the battery | SSH and query PiSugar directly (`pisugar-shell`), or the `device/power/` crate |

The Round-2 architecture decision — validation stages living in the
on-Pi companion binary `yoyopod-on-pi` rather than driving SSH from the
dev machine — is documented in the runtime guide's
[Testing & Validation](/runtime/testing/).

:::note[Canonical source]
Condensed from
[`docs/ROADMAP.md`](https://github.com/attmous/yoyopod/blob/main/docs/ROADMAP.md)
— a dated snapshot; when this page and the canonical doc disagree, the
canonical doc (and then the code) wins.
:::
