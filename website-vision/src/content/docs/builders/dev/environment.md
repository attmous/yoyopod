---
title: Dev Environment
description: Toolchain and repo orientation.
---

*From clean machine to building the workspace.*

## Overview

This page takes a contributor from a clean machine to a first successful
host build: Rust toolchain installed, repository cloned, the device
workspace and the CLI both compiling. Flashing and deploying to hardware
is the next page — [Build & Flash a Device](/builders/dev/build-and-flash/).
The repository is https://github.com/attmous/yoyopod; the reading order
for newcomers is the repo `README.md` → `docs/README.md` → the
Development Guide and Contributor Workflow on the as-built docs site.

## Toolchain

Rust stable via `rustup`, with `rustfmt` and `clippy`:

```bash
rustup default stable
rustup component add rustfmt clippy
cargo build --manifest-path cli/Cargo.toml --release
cargo install --path cli/yoyopod          # optional: `yoyopod` into ~/.cargo/bin
cargo build --manifest-path device/Cargo.toml --release -p yoyopod-runtime
```

`gh` must be authenticated — `yoyopod target deploy` uses it to fetch CI
artifacts. One naming trap: the installed `yoyopod` binary is the
**dev-machine operator CLI** — it does *not* launch the app runtime,
which runs on the device under systemd.

### The fast local check loop

```bash
cargo check --manifest-path device/Cargo.toml --workspace --locked
cargo test  --manifest-path cli/Cargo.toml
# targeted while iterating:
cargo check --manifest-path device/Cargo.toml -p yoyopod-ui --locked
```

Config validates without hardware:
`cargo run --manifest-path device/Cargo.toml -p yoyopod-runtime -- --config-dir config --dry-run`.

## Repo orientation

| Directory | Contents |
| --- | --- |
| `device/` | the Rust workspace: runtime, domain workers, and the LVGL-based UI |
| `cli/` | the `yoyopod` operator CLI, built separately from the device workspace |
| `config/` | tracked configuration; secrets stay untracked (`calling.secrets.yaml` or env) |
| `data/` | mutable data (contacts, recent tracks), seeded from tracked seed files |
| `website/` | the as-built engineering docs site |
| `website-vision/` | this site: target-state and vision docs |

Doc paths by area, per the contributor workflow: runtime work starts in
`device/runtime/` then the worker crate; Pi and setup work follows the
Setup Contract and Pi Dev Workflow; UI work follows the UI System Guide
— all on the as-built docs site. Current hotspots where extra care
pays: `device/runtime/` (supervision), `device/ui/` and LVGL scene code
(visual fidelity on hardware), and `cli/yoyopod/` (active rebuild).

## Today vs. target

Today, host builds of the Rust workspace and the CLI are the daily
loop, and hardware work targets the Pi-based prototype. `yoyopod setup …`
automation is paused during the CLI rebuild — dependencies are installed
manually per the setup contract — so the target of a scripted from-zero
setup that a new contributor finishes in one sitting is not yet real.
(`yoyopod dev profile` is likewise paused; use `cargo flamegraph`,
`samply`, or `perf`.) The planned `apps/` (parent app) and `packages/`
(SDK) directories do not exist yet; their environment story arrives with
them.

## Open questions

- TODO: What is the officially supported host OS matrix for contributors (Windows, macOS, Linux)?
- TODO: Which toolchain versions do we pin, and where is the single source of truth for them?

:::note[Sources]
Condensed from
[`docs/operations/DEVELOPMENT_GUIDE.md`](https://github.com/attmous/yoyopod/blob/main/docs/operations/DEVELOPMENT_GUIDE.md)
and
[`docs/operations/CONTRIBUTOR_WORKFLOW.md`](https://github.com/attmous/yoyopod/blob/main/docs/operations/CONTRIBUTOR_WORKFLOW.md)
and the as-built docs site (`website/` in the repository): the
Development Guide and Contributor Workflow pages.
:::
