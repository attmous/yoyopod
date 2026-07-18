---
title: Work Areas
description: Where a change belongs — the Rust crate ownership map and the monorepo boundaries.
---

yoyopod is Rust-first for the device runtime. This is the routing table:
for any change, the directory that owns it.

## The device crates

| Area | Owns | Deep docs |
| --- | --- | --- |
| `device/runtime/` | process supervision, config loading, event routing, state composition, UI snapshot delivery | [Runtime Guide](/runtime/) |
| `device/ui/` | Whisplay/LVGL rendering and button-facing UI behavior | [UI System Guide](/ui/) |
| `device/media/` | local music playback and mpv process control | [profile](/runtime/workers/media/) |
| `device/voip/` | SIP, calls, voice messages via Liblinphone | [profile](/runtime/workers/voip/) |
| `device/network/` | cellular modem, PPP, GPS | [profile](/runtime/workers/network/) |
| `device/cloud/` | MQTT/cloud telemetry and command transport | [profile](/runtime/workers/cloud/) |
| `device/power/` | power/battery integration | [profile](/runtime/workers/power/) |
| `device/speech/` | cloud speech, TTS, Ask worker | [profile](/runtime/workers/speech/) |

## The monorepo boundaries

- `apps/` — future web/mobile applications. **Device runtime code must
  never depend on `apps/`.**
- `packages/` — shared app/cloud contracts and SDKs; shared contracts
  should flow through `packages/contracts/` *when that package exists*
  (it is intended, not guaranteed present).
- `cli/` — the Rust operator CLI (`yoyopod target …`); rebuilding in
  rounds, status in the [Roadmap](/product/roadmap/).
- `deploy/` — systemd units, installer scripts, slot/release packaging.

## Disposable output — never work from, never commit

`device/target/` · `device/*/build/` · `cli/target/` · `logs/` · local
`data/`. Don't commit runtime models, preview bundles, audio files,
fonts, or build artifacts — large assets belong in a release artifact or
a package download step, only after deciding they're part of the source
contract. Clean with `git clean -fdX` (from a clean worktree only — it
deletes *all* ignored local files).

:::note[Canonical source]
Condensed from
[`docs/architecture/WORK_AREAS.md`](https://github.com/attmous/yoyopod/blob/main/docs/architecture/WORK_AREAS.md).
:::
