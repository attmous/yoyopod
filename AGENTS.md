# YoYoPod - Agent Instructions

Last Updated: 2026-05-13
Target Hardware: Raspberry Pi Zero 2W
Project: Rust-first iPod-inspired VoIP + local music device with small-screen button UI

**CLI rebuild in progress.** The Python operator CLI (`yoyopod_cli/`) was
deleted 2026-05-13. A new Rust CLI is being built at `cli/` in rounds.
Many `yoyopod ...` commands are temporarily unavailable. See
`docs/ROADMAP.md` for the roadmap and workarounds.

Purpose
- Keep this file small. It is the always-loaded agent brief, not a full design doc.
- Current code beats old plans.

Guidance order
1. Current Rust code in `device/` (runtime, workers) and `cli/` (operator CLI)
2. `docs/ROADMAP.md` for what's broken right now
3. `README.md`, `docs/README.md`, and current operation docs
4. `rules/` for constraints and style
5. `skills/` for deploy/debug playbooks (many are stale during the rebuild)
6. Historical plans only when they match current code

Read these rules first
- `rules/project.md`
- `rules/architecture.md`
- `rules/code-style.md`
- `rules/design-fidelity.md`
- `rules/voip.md`
- `rules/lvgl.md`
- `rules/logging.md`
- `rules/deploy.md`

Canonical deploy/debug skills (NOTE: many call deleted yoyopod_cli
commands during the rebuild — see ROADMAP.md)
- `skills/yoyopod-deploy/SKILL.md`
- `skills/yoyopod-sync/SKILL.md`
- `skills/yoyopod-logs/SKILL.md`
- `skills/yoyopod-restart/SKILL.md`
- `skills/yoyopod-status/SKILL.md`
- `skills/yoyopod-screenshot/SKILL.md`
- `skills/yoyopod-rust-artifact/SKILL.md`
- `docs/operations/archive/SLOT_DEPLOY.md` for prod slot/OTA-ready flow

Current Runtime Status
- Rust is the only runtime. The top-level Rust entrypoint is
  `device/runtime/src/main.rs`, binary `yoyopod-runtime`.
- `yoyopod-runtime` loads config, owns PID/log lifecycle, supervises worker
  processes, routes worker events, composes app state, and sends UI snapshots.
- Rust worker domains live under:
  - `device/ui/` for Whisplay UI and LVGL rendering
  - `device/media/` for local music/mpv ownership
  - `device/voip/` for Liblinphone/SIP ownership
  - `device/network/` for SIM7600/PPP/GPS ownership
  - `device/cloud/` for cloud MQTT telemetry/command transport
- The Rust UI host contains native Rust LVGL scene controllers for the main
  screen set. The only C dependency in the LVGL display path is the pinned
  upstream LVGL native library.
- The operator CLI is in transition from Python to Rust; see
  `docs/ROADMAP.md`. Rust CLI source: `cli/`.
- Dev service runs the Rust runtime directly through `yoyopod-runtime`.

Pi Lanes And Bootstrap
- Dev lane: mutable hardware-testing checkout at `/opt/yoyopod-dev/checkout`,
  service `yoyopod-dev.service`.
- Prod lane: immutable packaged slots under `/opt/yoyopod-prod`, service
  `yoyopod-prod.service`. New prod release builds are blocked until Round 3
  of the CLI rebuild (see ROADMAP.md).
- Check lane ownership first with `yoyopod target mode status`; dev/prod
  services should not own hardware together.
- Dev deploy loop: `yoyopod target mode activate dev`, then
  `yoyopod target deploy --branch <branch>`. The deploy command pushes,
  finds the matching CI artifact, syncs the Pi checkout, installs the
  binaries, restarts the service, and verifies startup in one step.
- Rust binary deploy rule: commit and push first; `yoyopod target deploy`
  always uses GitHub Actions artifacts for the exact commit. Do not build
  Rust binaries on the Pi Zero 2W unless the user explicitly overrides
  this rule.

Source Of Truth
- `device/runtime/`
- `device/cloud/`
- `device/ui/`
- `device/media/`
- `device/voip/`
- `device/network/`
- `deploy/systemd/yoyopod-dev.service`
- `deploy/systemd/yoyopod-prod.service`
- `cli/` (Rust operator CLI, in-progress)
- `docs/ROADMAP.md`
- `docs/operations/DEV_PROD_LANES.md`
- `docs/operations/PI_DEV_WORKFLOW.md` (some content stale during rebuild)
- `docs/operations/archive/SLOT_DEPLOY.md` (stale during rebuild; Round 3)
- `docs/architecture/SYSTEM_ARCHITECTURE.md`
- `docs/architecture/CANONICAL_STRUCTURE.md`

High-Value Commands
- Rust device workspace check: `cargo check --manifest-path device/Cargo.toml --workspace --locked`
- Rust runtime check: `cargo check --manifest-path device/Cargo.toml -p yoyopod-runtime --locked`
- Rust UI check: `cargo check --manifest-path device/Cargo.toml -p yoyopod-ui --locked`
- Rust runtime dry run: `cargo run --manifest-path device/Cargo.toml -p yoyopod-runtime -- --config-dir config --dry-run`
- Rust CLI build: `cargo build --manifest-path cli/Cargo.toml --release`
- Pi lane status: `yoyopod target mode status`
- Pi deploy + verify: `yoyopod target deploy --branch <branch> [--sha <sha>]`
- See `cli/README.md` for the full Rust CLI command reference.

Verification Policy
- Prefer Rust build checks for code changes (`cargo check`/`cargo test`
  inside `device/` and `cli/`).
- For hardware work, exact-commit CI artifacts (`yoyopod-rust-device-arm64-<sha>`)
  and Pi results matter most. Always report the commit SHA, artifact names,
  and hardware command/result.
- Automated on-Pi validation: `yoyopod target validate` runs the staged
  suite (deploy, smoke, stability + optional soaks) via the `yoyopod-on-pi`
  binary shipped in the CI artifact. The voip / cloud-voice stages are a
  Round 2 follow-up; validate those manually via journalctl + hardware
  inspection.

Hardware
- The supported hardware is the Raspberry Pi Zero 2W + PiSugar Whisplay
  HAT (portrait 240x280, single side button, microphone, speaker) +
  PiSugar 3 power module. No other displays, input HATs, or boards are
  supported.

Guardrails
- Prefer `yoyopod target` over ad-hoc SSH sequences.