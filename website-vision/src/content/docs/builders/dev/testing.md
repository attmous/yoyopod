---
title: Testing & Validation
description: What green means, on host and on hardware.
---

*The testing story: host tests, on-device validation stages, and CI.*

## Overview

The layered model is real today: fast host checks first, then the Pi as
the actual validation target for runtime, display, input, audio, SIP,
modem, and power. The policy behind it is as much about honesty as
coverage — report checks that *ran*, not checks that should have run. A
hardware validation report states the branch and exact commit SHA, the
artifact name and CI run ID it deployed, the Pi command results, whether
the dev service was left running, and the manual steps performed with
their outcomes.

## On the host

Rust checks are focused per changed crate, widening as the change does:

```bash
cargo check --manifest-path device/Cargo.toml -p yoyopod-ui --locked   # per crate
cargo check --manifest-path device/Cargo.toml --workspace --locked     # broad change
# CLI changes get all three:
cargo check  --manifest-path cli/Cargo.toml
cargo test   --manifest-path cli/Cargo.toml
cargo clippy --manifest-path cli/Cargo.toml --all-targets
```

Wire-level integration tests use `device/harness`, a small test library
that decodes a worker's raw stdout bytes into typed envelopes and panics
loudly on any malformed line. Because it depends on `yoyopod-protocol`
itself, tests assert against the exact wire format the workers speak —
they cannot drift from the protocol any more than the workers can.

One hard limit: for native LVGL / display-hardware changes, green host
checks are **not** parity. Validate against the CI-built ARM artifact
for the exact commit before claiming hardware works.

## On the device

`device/onpi` builds `yoyopod-on-pi`, the on-device validator:
cross-compiled to arm64, shipped in the CI bundle, and designed to run
on the Pi via `yoyopod target validate` over SSH. Exit codes are the
contract: **0 pass · 1 fail · 2 blocked**.

| Stage | Checks |
| --- | --- |
| `smoke` | the 8 worker binaries exist and are executable; required config present; systemd units in place; runtime `--dry-run` emits valid JSON |
| `deploy` | deploy-layout assertions (paths, permissions) |
| `stability` | the runtime stays up under observation |
| `navigation` | drives the real `yoyopod-ui-host` over the real envelope protocol: ticks at 500 ms, requires frames ≥ 1, the LVGL renderer, and a non-empty active screen |
| `lvgl` | display-backend specific checks |
| `voip`, `cloud-voice` | **stubbed — exit 2** |

The navigation stage is the closest thing to an end-to-end UI test on
real hardware: same binary, same protocol, same LVGL as production —
only the tick cadence differs. One honest caveat: the `target validate`
command that drives these stages is paused until Round 2 of the CLI
rebuild, so today on-device validation is run manually —
`target status`, `target logs --follow`,
`journalctl -u yoyopod-dev.service -f`, and human eyes on the changed
surface.

## Today vs. target

Today: the host checks above, the validator stages shipped in every CI
bundle but invoked manually until Round 2, and the call-domain stages
(`voip`, `cloud-voice`) stubbed. Domain validation as the vision states
it — a whitelisted call connects, a voice message round-trips, location
updates arrive (live-ish, not real-time) — is not yet automated, and
battery/soak measurement has no defined method yet. Target: `target
validate` restored as the single command that runs the staged checks,
the stubbed stages filled in, and coverage expectations for the future
parent app and SDK packages once they exist.

## Open questions

- TODO: How do we test 4G and GPS behavior repeatably — field procedure, lab setup, or simulation?
- TODO: How are battery drain and long-running soak stability measured, and against what thresholds?
- TODO: What is the minimal on-device checklist a *release* must pass, once prod slot publishing (Round 3) exists?

:::note[Sources]
Condensed from
[`docs/operations/QUALITY_GATES.md`](https://github.com/attmous/yoyopod/blob/main/docs/operations/QUALITY_GATES.md)
and the as-built docs site (`website/` in the repository): the Testing
& Validation page of the Runtime Guide and the Quality Gates page.
:::
