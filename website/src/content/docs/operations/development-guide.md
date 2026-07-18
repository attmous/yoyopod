---
title: Development Guide
description: Toolchain, configuration, running, validation, and the Pi workflow — the operational reference hub.
---

The day-one reference: how to build, run, and validate yoyopod from a
fresh checkout. Reading order for newcomers: repo `README.md` →
`docs/README.md` → [Contributor Workflow](/operations/contributor-workflow/)
→ [System overview](/runtime/overview/) → the [Roadmap](/product/roadmap/).

## Toolchain

```bash
rustup default stable
rustup component add rustfmt clippy
cargo build --manifest-path cli/Cargo.toml --release
cargo install --path cli/yoyopod          # optional: `yoyopod` into ~/.cargo/bin
cargo build --manifest-path device/Cargo.toml --release -p yoyopod-runtime
```

`gh` must be authenticated — `yoyopod target deploy` uses it to fetch CI
artifacts. Pi system dependencies (mpv, liblinphone, ALSA, i2c-tools,
pisugar-server, ppp) are the [Setup Contract](/operations/setup-contract/)'s
department.

## Running

```bash
# validate config without hardware:
cargo run --manifest-path device/Cargo.toml -p yoyopod-runtime -- --config-dir config --dry-run
# run the runtime locally:
device/target/release/yoyopod-runtime --config-dir config
```

:::caution[Two different "yoyopod"s]
The installed `yoyopod` binary is the **dev-machine operator CLI** — it
does *not* launch the runtime. The app runtime runs on the Pi via
`yoyopod-dev.service` / `yoyopod-prod.service`.
:::

## Configuration

Tracked config lives under `config/` — the full topology and ownership
rules are on [Canonical Structure](/architecture/canonical-structure/),
and the per-worker wiring on
[Configuration Wiring](/runtime/configuration/). Secrets go in
`calling.secrets.yaml` (untracked) or env; mutable data (contacts,
recent tracks) lives under `data/`, seeded from tracked seed files.

One behavior worth knowing: contacts may carry both `sip_address` and
`phone_number`; the runtime prefers SIP while GSM is disabled, and
backend sync replaces the cloud-managed subset while preserving
local-only contacts.

## Validation

```bash
cargo check --manifest-path device/Cargo.toml --workspace --locked
cargo test  --manifest-path cli/Cargo.toml
cargo clippy --manifest-path cli/Cargo.toml --all-targets
```

The full policy — what counts as verification and what to report — is
[Quality Gates](/operations/quality-gates/).

## The Pi workflow, in one block

```bash
yoyopod target config edit                 # one-time per machine
yoyopod target mode activate dev
yoyopod target deploy --branch <branch>    # or --sha <commit>
yoyopod target status
yoyopod target logs --follow --filter ERROR
```

Details, flags, and troubleshooting:
[Pi Dev Workflow](/operations/pi-dev-workflow/). App logs land in
`logs/yoyopod.log` + `logs/yoyopod_errors.log`; deploy connection
defaults live in `deploy/pi-deploy.yaml` with machine-specific values in
the gitignored `pi-deploy.local.yaml`.

## Paused during the CLI rebuild

Per the [Roadmap](/product/roadmap/): `yoyopod setup …` automation
(install manually), `yoyopod dev profile` (use `cargo flamegraph` /
`samply` / `perf`), and `yoyopod target validate` (Round 2 — validate
manually via journalctl until it lands).

:::note[Canonical source]
Condensed from
[`docs/operations/DEVELOPMENT_GUIDE.md`](https://github.com/attmous/yoyopod/blob/main/docs/operations/DEVELOPMENT_GUIDE.md).
:::
