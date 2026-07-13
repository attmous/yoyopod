# YoYoPod Roadmap

This is the project's living roadmap. It tracks the rounds of the Rust
CLI rebuild — what's done, what's paused, when each gap closes.

The most recent rebuild milestone is summarised at the top; rounds in
detail follow.

Status as of 2026-07-12:

| Round | Scope | State |
|---|---|---|
| 0 | Demolition + scaffolding | ✅ merged |
| 1 | Daily dev loop (`yoyopod target …` Rust MVP) | ✅ merged |
| 2 | Restore hardware validation (`yoyopod target validate`) | 🔄 in progress |
| 3 | Restore prod release pipeline | ⏳ not started |
| 4+ | Diagnostics (`pi voip/power/network/rust-ui-host`) | ⏳ not started |

## What happened

The Python operator CLI (`yoyopod_cli/`, ~21k LOC) was deleted in one
move. A new Rust CLI is being built from scratch at `cli/`, in rounds,
on a business-need basis. Each round restores a slice of capability.

This document is the honesty doc: what is broken today, what works,
when it gets fixed.

## Why

The Python CLI grew to cover dev-machine orchestration, on-Pi diagnostics,
slot release tooling, and library code consumed by deploy scripts. After
the runtime transitioned to Rust (no Python runtime path remains), most
of that surface area no longer fits its original shape. Porting the
Python CLI line-by-line would have rebuilt assumptions that no longer
hold (e.g. `target sync` as a thin `git pull + restart` step, valid only
when source files were the executable).

Building new in rounds lets each restored capability match current
reality, not historical reality.

## What works today

- The dev runtime (`yoyopod-dev.service` execs
  `device/runtime/build/yoyopod-runtime` directly — no Python in the path).
- The prod runtime on already-shipped slots
  (`/opt/yoyopod-prod/current/bin/launch` — no Python in the path).
- CI's `rust-device-arm64` job continues to produce the
  `yoyopod-rust-device-arm64-<sha>` artifact for each push/PR.
- All Rust workspace commands (`cargo check`, `cargo build`,
  `cargo test`) under `device/Cargo.toml`.

## What is broken today

- **Prod slot builds.** CI's `slot-arm64` job and the `release.yml`
  workflow are disabled. No new prod tarballs can be produced.
- **Prod slot install preflight on the Pi.** `install_release.sh` still
  runs end-to-end but the structural preflight is a no-op. Slots
  shipped before the deletion still contain a bundled preflight module.
- **Diagnostics** (`pi voip`, `pi power`, `pi network`, `pi
  rust-ui-host`). Gone with the Python CLI. SSH manually or read code.
- **VoIP + cloud-voice validation stages.** `yoyopod-on-pi validate
  {voip, cloud-voice}` are stubs (exit 2) until the Round 2 follow-up
  ports them. The base stages (deploy, smoke, stability, navigation,
  lvgl) are restored by the in-flight Round 2 work.
- **The `yoyopod` console script.** Replaced by the Rust binary
  installed from `cli/`.

## Rounds

### Round 0 — Demolition + scaffolding ✅

Deleted `yoyopod_cli/`, `scripts/build_release.py`, `pyproject.toml`,
`.python-version`, `scripts/quality.py`. Neutered `install_release.sh`
preflight. Marked `deploy/docker/slot-builder.Dockerfile` deprecated.
Disabled CI jobs that depended on the deleted code. Scaffolded the
Rust workspace at `cli/`. Wrote this document.

### Round 1 — Daily dev loop ✅

Rust binary at `cli/yoyopod/` with nine commands covering the inner
dev loop:

```
yoyopod target config edit
yoyopod target mode {status, activate}
yoyopod target deploy [--branch B] [--sha S] [--clean-native] [--wait-for-ci]
yoyopod target {status, restart, logs, screenshot}
yoyopod target validate   (stub — see Round 2)
```

`target deploy` is the centrepiece: it pushes, finds the CI run for
the exact commit, downloads the `yoyopod-rust-device-arm64-<sha>`
artifact, syncs the Pi checkout, scps and extracts the binaries,
restarts the dev service, and verifies startup. Replaces the manual
flow that `skills/yoyopod-rust-artifact/SKILL.md` used to document.

### Round 2 — Restore hardware validation 🔄 (started 2026-07-12)

**Architecture decision (made at round start, 2026-07-12):** the
validation stages live in a new on-Pi companion binary, `yoyopod-on-pi`
(`device/onpi/`), executed on the Pi by `yoyopod target validate` over
SSH. The alternative (driving stages from the dev machine over
per-command SSH) was rejected because:

- The stages supervise worker binaries over their stdin/stdout envelope
  protocol (spawn `yoyopod-ui-host`, send `ui.runtime_snapshot` /
  `ui.input_action`, assert on `ui.health`). That needs a long-lived
  process on the Pi, not SSH round-trips.
- Living in the `device/` workspace, the validator consumes
  `yoyopod-protocol` directly, so it cannot drift from what the
  workers actually speak.
- CI ships it inside the existing `yoyopod-rust-device-arm64-<sha>`
  bundle, so `target deploy` installs it automatically and validation
  always matches the deployed commit. Round 4+ diagnostics can join
  the same binary later.

In flight now: stages `deploy`, `smoke`, `stability`, `navigation`,
`lvgl` ported to Rust (Python-era venv/entrypoint checks dropped for
Rust reality), plus `target validate` orchestration with the same
committed-code contract as `target deploy`.

Round 2 follow-up (next): port the `voip` stage (SIP registration +
call soak) and the `cloud-voice` stage (STT/TTS worker boundary
checks) from the old `voip.py` / `cloud_voice.py`. Until then those
stages exit 2 with a clear message.

Restores: hardware validation as part of the daily loop.

### Round 3 — Restore prod release pipeline

Port `release_manifest`, `slot_contract`, slot tarball builder, and
`health preflight` to Rust. Replace `scripts/build_release.py`. Rewire
`install_release.sh` to call the Rust binary bundled inside slots.
Re-enable CI's `slot-arm64` and `release` jobs.

Restores: prod release capability.

### Round 4+ — Diagnostics, as needed

`pi voip {check, debug}`, `pi power {battery, rtc}`, `pi network
{status, probe}`, `pi rust-ui-host`, and any other gap that proves
painful enough to fix. Each is its own small round.

## Workarounds during the gap

- **Need to validate a Rust change on hardware before Round 2 lands?**
  Use `yoyopod target deploy` (Round 1), then SSH in and inspect the
  service: `systemctl status yoyopod-dev.service`, `journalctl -u
  yoyopod-dev.service -f`, hardware inspection.
- **Need to ship a prod release before Round 3 lands?** You can't.
  Plan release windows around the rebuild.
- **Need an old-school `yoyopod pi power battery` reading?** SSH to the
  Pi and read the PiSugar values directly (`pisugar-server` /
  `/proc/...`), or read the relevant Rust crate under `device/power/`.

## Pointers

- Rust CLI source: [`../cli/`](../cli/)
- Rust CLI docs: [`../cli/README.md`](../cli/README.md)
- Paused capability docs: [`operations/archive/`](operations/archive/)
- This file: `docs/ROADMAP.md`
