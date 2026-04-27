# Contributor Workflow

This guide is the shortest path from fresh checkout to a credible YoYoPod contribution.

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

Use the repo-owned setup contract first:

```bash
uv run yoyopod setup host
uv run yoyopod setup verify-host
```

This is the baseline executable setup contract.

It is not the same thing as complete setup ownership. Feature-specific assets and unusual hardware edges can still need extra follow-through.

Before you start a workflow that depends on more than local simulation and CI-safe checks, verify the extra host prerequisites explicitly:

```bash
uv run yoyopod setup verify-host --with-remote-tools
uv run yoyopod setup verify-host --with-github
```

Use `--with-remote-tools --with-github` together when you plan to both validate on a Raspberry Pi over SSH and use GitHub CLI helpers for branch or PR work.

## Fast local loop

Simulation run:

```bash
yoyopod build simulation
python yoyopod.py --simulate
```

Core validation loop:

```bash
uv run python scripts/quality.py gate
uv run pytest -q
uv run python scripts/quality.py ci
```

Full quality debt audit:

```bash
uv run python scripts/quality.py audit
```

CI currently runs `uv run python scripts/quality.py gate` plus `uv run pytest -q`.
Use `uv run python scripts/quality.py ci` as the local wrapper when you want both in one command.
Use `audit` when you want to see the broader repo debt without pretending it is all gated yet.

## Choose the right doc path for the work

### Runtime and orchestration work

Read:

1. [`SYSTEM_ARCHITECTURE.md`](../architecture/SYSTEM_ARCHITECTURE.md)
2. subsystem docs for the area you are touching
3. `rules/architecture.md`
4. the relevant files under `yoyopod/`

Current reality:

- `YoyoPodApp` is thinner than before, but runtime cleanup is still in progress
- `yoyopod/core/bootstrap/` is the current boot hotspot, not the final architecture destination
- runtime/state/model cleanup should prefer clearer ownership over broad rewrites

### Raspberry Pi and setup work

Read:

1. [`SETUP_CONTRACT.md`](SETUP_CONTRACT.md)
2. [`DEVELOPMENT_GUIDE.md`](DEVELOPMENT_GUIDE.md)
3. [`PI_DEV_WORKFLOW.md`](PI_DEV_WORKFLOW.md)
4. [`RPI_SMOKE_VALIDATION.md`](RPI_SMOKE_VALIDATION.md)
5. `rules/deploy.md`

Baseline commands:

```bash
uv run yoyopod setup verify-host --with-remote-tools
yoyopod remote config edit
uv run yoyopod remote setup --with-pisugar
uv run yoyopod remote verify-setup --with-pisugar
yoyopod remote validate --branch <branch> --sha <commit> --with-music --with-voip
```

These are the canonical contributor-path commands.
Add `--with-voice` and/or `--with-network` when the target needs the TTS or modem paths.
For direct on-Pi validation commands such as `yoyopod pi validate smoke`, use [`RPI_SMOKE_VALIDATION.md`](RPI_SMOKE_VALIDATION.md).

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

At minimum, run the same validation commands CI enforces today:

```bash
uv run python scripts/quality.py gate
uv run pytest -q
```

`uv run python scripts/quality.py ci` is the local convenience wrapper for those same two steps.

Then add any focused commands relevant to your area, for example:

```bash
python -m compileall yoyopod tests demos scripts
uv run pytest -q tests/e2e/test_app_orchestration.py
uv run pytest -q tests/cli/test_setup_cli.py tests/cli/test_cli.py
```

If your change is outside the currently gated surface, say so plainly in the PR instead of pretending CI covered more than it did.

## What a good PR looks like here

A good YoYoPod PR:

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

- `yoyopod/core/bootstrap/`
- `yoyopod/core/application.py`
- `yoyopod/core/bus.py`
- `yoyopod/core/scheduler.py`
- `yoyopod/core/app_context.py`
- duplicated domain/state models that drift across layers
- setup/docs wording that can overstate what the new commands guarantee

## If you only remember one thing

Be honest about the repo’s current state.

This project is making real foundation progress, but it is still alpha. The right move is to land executable improvements without pretending the remaining debt disappeared.
