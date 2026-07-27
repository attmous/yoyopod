# Contributor Workflow

This guide is the shortest path from fresh checkout to a credible yoyopod contribution.

It is not a full architecture document and it is not a board bringup manual.

It is the day-to-day contributor path.

## Read this first

If you are new here, read in this order:

1. [`../README.md`](../../README.md)
2. [`README.md`](../README.md)
3. [`DEVELOPMENT_GUIDE.md`](DEVELOPMENT_GUIDE.md)
4. [`SYSTEM_ARCHITECTURE.md`](../architecture/SYSTEM_ARCHITECTURE.md)
5. [`QUALITY_GATES.md`](QUALITY_GATES.md)
6. `rules/project.md`
7. `rules/architecture.md`

## Baseline local setup

Automated host setup tooling (`yoyopod setup host` / `verify-host`) was
deleted in Round 0 of the CLI rebuild and has not yet been ported back.
See [`../ROADMAP.md`](../ROADMAP.md). Until then, install
dependencies manually:

- a Rust stable toolchain via `rustup`
- `gh` (GitHub CLI) authenticated for `yoyopod target deploy`
- standard Pi-side prereqs (`ssh`, `scp`, `git`)

Then build the Rust CLI and (optionally) install it into PATH:

```bash
cargo build --manifest-path cli/Cargo.toml --release
cargo install --path cli/yoyopod
```

## Fast local loop

Rust workspace check (preferred):

```bash
cargo check --manifest-path device/Cargo.toml --workspace --locked
cargo test  --manifest-path cli/Cargo.toml
```

Run targeted crate checks during iteration on a specific worker
(`-p yoyopod-runtime`, `-p yoyopod-ui`, etc.). See
[`QUALITY_GATES.md`](QUALITY_GATES.md).

## Choose the right doc path for the work

### Runtime and orchestration work

Read:

1. `device/runtime/`
2. the relevant Rust worker crate under `device/`
3. [`SYSTEM_ARCHITECTURE.md`](../architecture/SYSTEM_ARCHITECTURE.md)
4. subsystem docs for the area you are touching
5. `rules/architecture.md`

Current reality:

- `yoyopod-runtime` owns top-level runtime state and worker supervision.
- The operator CLI is Rust (`cli/`), currently rebuilding in rounds.
- No Python code remains in tree.

### Raspberry Pi and setup work

Read:

1. [`SETUP_CONTRACT.md`](SETUP_CONTRACT.md)
2. [`DEVELOPMENT_GUIDE.md`](DEVELOPMENT_GUIDE.md)
3. [`PI_DEV_WORKFLOW.md`](PI_DEV_WORKFLOW.md)
4. [`archive/RPI_SMOKE_VALIDATION.md`](archive/RPI_SMOKE_VALIDATION.md)
5. `rules/deploy.md`

Baseline commands:

```bash
yoyopod target config edit
yoyopod target mode activate dev
yoyopod target deploy --branch <branch>           # or --sha <commit>
yoyopod target logs --follow
```

`yoyopod target deploy` is the everyday command — it pushes, fetches
the CI artifact, syncs the Pi, installs binaries, restarts, and
verifies startup in one step.

Automated on-Pi validation (`yoyopod target validate`) is a Round 1
stub during the CLI rebuild; validate manually after deploy. See
[`archive/RPI_SMOKE_VALIDATION.md`](archive/RPI_SMOKE_VALIDATION.md).

### Docs and contributor guidance work

Read:

1. [`README.md`](../../README.md)
2. [`README.md`](../README.md)
3. this file
4. `rules/project.md`
5. `rules/architecture.md`

When updating docs:

- prefer source-of-truth docs over plan docs
- keep the staged-vs-complete distinction honest
- do not describe debt as solved just because a baseline contract exists

## Before opening a PR

At minimum, run the relevant Rust build check:

```bash
cargo check --manifest-path device/Cargo.toml --workspace --locked
cargo test  --manifest-path cli/Cargo.toml      # if you touched cli/
```

For hardware-touching work, run a deploy and a manual eyes-on check:

```bash
yoyopod target deploy --branch <branch>
yoyopod target status
yoyopod target logs --follow
```

If your change is outside the currently gated surface, say so plainly
in the PR instead of pretending CI covered more than it did.

## What a good PR looks like here

A good yoyopod PR:

- stays within one coherent problem slice
- updates docs when the contract changes
- says exactly what is now enforced vs still debt
- avoids fake completeness
- leaves the repo more navigable than before

## Current contributor traps

Watch for these recurring mistakes:

- treating the staged quality gate as whole-repo cleanliness
- treating the setup contract as fully solved setup ownership
- mixing unrelated cleanup into architecture PRs
- moving complexity into a new file and calling the architecture done
- updating plan docs while leaving source-of-truth docs stale

## Current hotspots

These are good places to be extra careful:

- `device/runtime/` — top-level runtime supervision
- `device/ui/` + LVGL scene controllers — visual fidelity on real hardware
- `cli/yoyopod/` — operator surface (under active rebuild; see
  [`../ROADMAP.md`](../ROADMAP.md))
- duplicated domain/state models that drift across `device/` crates
- setup/docs wording that overstates what the rebuilt CLI guarantees today

## If you only remember one thing

Be honest about the repo’s current state.

This project is making real foundation progress, but it is still alpha. The right move is to land executable improvements without pretending the remaining debt disappeared.
