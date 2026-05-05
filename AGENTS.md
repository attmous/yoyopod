# YoYoPod - Agent Instructions

Last Updated: 2026-05-01
Target Hardware: Raspberry Pi Zero 2W
Project: Rust-first iPod-inspired VoIP + local music device with small-screen button UI

Purpose
- Keep this file small. It is the always-loaded agent brief, not a full design doc.
- Current code beats old plans. Treat Python runtime docs as legacy unless the
  current code still routes through them.

Guidance order
1. Current Rust code in `yoyopod_rs/`
2. Current deploy/runtime code in `deploy/`, `yoyopod_cli/`, and `yoyopod/`
3. `README.md`, `docs/README.md`, and current operation docs
4. `rules/` for constraints and style
5. `skills/` for deploy/debug playbooks
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

Canonical deploy/debug skills
- `skills/yoyopod-deploy/SKILL.md`
- `skills/yoyopod-sync/SKILL.md`
- `skills/yoyopod-logs/SKILL.md`
- `skills/yoyopod-restart/SKILL.md`
- `skills/yoyopod-status/SKILL.md`
- `skills/yoyopod-screenshot/SKILL.md`
- `skills/yoyopod-rust-artifact/SKILL.md`
- `docs/operations/SLOT_DEPLOY.md` for prod slot/OTA-ready flow

Current Runtime Status
- Rust is the target runtime owner. The top-level Rust entrypoint is
  `yoyopod_rs/runtime/src/main.rs`, binary `yoyopod-runtime`.
- `yoyopod-runtime` loads config, owns PID/log lifecycle, supervises worker
  processes, routes worker events, composes app state, and sends UI snapshots.
- Rust worker domains live under:
  - `yoyopod_rs/ui/` for Whisplay UI and LVGL rendering
  - `yoyopod_rs/media/` for local music/mpv ownership
  - `yoyopod_rs/voip/` for Liblinphone/SIP ownership
  - `yoyopod_rs/network/` for SIM7600/PPP/GPS ownership
  - `yoyopod_rs/cloud/` for cloud MQTT telemetry/command transport
- The Rust UI host now contains native Rust LVGL scene controllers for the main
  screen set. The C LVGL shim and LVGL native library still exist as display
  infrastructure during the transition.
- Python is no longer the architectural target for the app runtime. It remains
  for CLI/deploy tooling, compatibility paths, tests, and any domain that has
  not been fully removed yet.
- Dev service can run either owner. Rust is selected with
  `YOYOPOD_DEV_RUNTIME=rust`; the legacy fallback is `python yoyopod.py`.

Pi Lanes And Bootstrap
- Dev lane: mutable hardware-testing checkout at `/opt/yoyopod-dev/checkout`,
  venv at `/opt/yoyopod-dev/venv`, service `yoyopod-dev.service`.
- Prod lane: immutable packaged slots under `/opt/yoyopod-prod`, service
  `yoyopod-prod.service`; use `remote release ...`, not `remote sync`.
- Check lane ownership first with `yoyopod remote mode status`; dev/prod
  services should not own hardware together.
- Hard cut: supported runtime owners are only `yoyopod-dev.service` and
  `yoyopod-prod.service`; `yoyopod@*.service`, `yoyopod-slot.service`,
  unmanaged `python yoyopod.py`, and `remote service ...` are contamination
  paths.
- Dev deploy loop: `yoyopod remote mode activate dev`, then
  `yoyopod remote sync --branch <branch>`. Add `--clean-native` after
  native/CMake/lib changes or branch switches.
- Rust binary deploy rule: commit and push first, then use GitHub Actions
  artifacts for the exact commit under test. Do not build Rust binaries on the
  Pi Zero 2W unless the user explicitly overrides this rule.

Source Of Truth
- `yoyopod_rs/runtime/`
- `yoyopod_rs/cloud/`
- `yoyopod_rs/ui/`
- `yoyopod_rs/media/`
- `yoyopod_rs/voip/`
- `yoyopod_rs/network/`
- `deploy/systemd/yoyopod-dev.service`
- `deploy/systemd/yoyopod-prod.service`
- `yoyopod_cli/main.py`
- `yoyopod_cli/COMMANDS.md`
- `docs/operations/DEV_PROD_LANES.md`
- `docs/operations/PI_DEV_WORKFLOW.md`
- `docs/operations/SLOT_DEPLOY.md`
- `docs/architecture/DISPLAY_HAL_ARCHITECTURE.md`
- `docs/design/WHISPLAY_SIMULATION_PARITY_CONTRACT.md`
- `docs/superpowers/specs/2026-04-30-rust-runtime-host-design.md`

High-Value Commands
- Rust workspace tests: `cargo test --manifest-path yoyopod_rs/Cargo.toml --workspace --locked`
- Rust runtime tests: `cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime --locked`
- Rust UI tests: `cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-ui --locked`
- Rust runtime dry run: `cargo run --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime -- --config-dir config --dry-run`
- Build local artifact on development machine: `uv run yoyopod build rust-runtime`
- Pi lane status: `yoyopod remote mode status`
- Pi validation: `yoyopod remote validate --branch <branch> --sha <commit>`
- Remote operations: `yoyopod remote ...`
- Command reference: `yoyopod_cli/COMMANDS.md`

Verification Policy
- Do not run the old Python quality gate by default. It is no longer the
  required pre-commit/pre-push path for Rust runtime work.
- Prefer Rust checks for Rust changes. Run targeted Python tests only when the
  changed surface is Python CLI/deploy/compatibility code.
- For hardware work, exact-commit CI artifacts and the Pi result matter more
  than local Python gates. Always report the commit SHA, artifact names, and
  hardware command/result.
- If a CI failure is specifically in Python tooling, fix and verify that Python
  surface directly; do not let it block unrelated Rust runtime iteration.

Hardware Modes
- PiSugar Whisplay: portrait + single button; primary Rust target.
- Pimoroni Display HAT Mini: landscape + four buttons on shared LVGL path.
- Simulation: shared LVGL/browser preview remains useful for UI comparison but
  does not replace Whisplay hardware checks.

Guardrails
- Prefer narrow, reviewable changes.
- Keep raw LVGL confined to display/LVGL binding layers.
- Prefer `yoyopod remote` over ad-hoc SSH sequences.
- Use current Rust code and hardware evidence as truth. `docs/history/`,
  `docs/archive/`, and older Python runtime docs are historical unless proven
  current.
