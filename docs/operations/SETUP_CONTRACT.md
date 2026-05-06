# Setup and System Dependency Contract

This document defines the baseline repo-owned setup and verification contract for YoYoPod Core.

Issue [`#87`](https://github.com/moustafattia/yoyopod-core/issues/87) is the work that turned this from wishful docs into executable commands. This file documents the contract those commands implement.

## Why this exists

The repo already owns a lot of runtime behavior, but setup still has too much implicit machine knowledge.

That is a foundation risk.

For this repo to be the real base of the system, a contributor should be able to answer these questions from the repo itself:

- what Python and system dependencies are required
- which dependencies are core vs feature-gated
- which files are repo-owned vs machine-local
- how to bring up a dev machine
- how to bring up a target Pi
- how to verify the setup before debugging product code

## Setup ownership rules

The repo should own:

- the Python dependency graph in `pyproject.toml`
- the shared Pi deploy contract in `deploy/pi-deploy.yaml`
- the tracked app config in `config/`
- the documented system dependency list in this file
- the validation commands in `docs/operations/DEVELOPMENT_GUIDE.md` and `docs/operations/RPI_SMOKE_VALIDATION.md`
- the remote workflow exposed through `yoyopod remote`

Machine-local values should stay out of tracked files.

Examples of machine-local state:

- Pi hostname or SSH alias
- Pi username
- machine-specific overrides in `deploy/pi-deploy.local.yaml`
- secrets and account credentials
- local audio paths or removable-media contents

## Supported setup surfaces

### 1. CI-safe developer machine

Minimum expectation:

- Python `3.12+`
- `uv`
- Git

Current repo-owned bootstrap baseline:

```bash
uv run yoyopod setup host
```

This is the executable baseline, not full setup ownership. It does not provision
external service credentials or cover every board-specific edge.
If `yoyopod` is invoked before the contributor CLI stack is present, it should
now exit with a short bootstrap hint instead of crashing during import.

Current repo-owned validation baseline:

```bash
uv run yoyopod setup verify-host
```

Optional but expected for Pi workflows:

- `ssh`
- `rsync`

Optional but useful for repo operations:

- `gh`

Workflow-specific host verification:

```bash
uv run yoyopod setup verify-host --with-remote-tools
uv run yoyopod setup verify-host --with-github
uv run yoyopod setup verify-host --with-remote-tools --with-github
```

Use the baseline command for local-only work. Add `--with-remote-tools` before using `yoyopod remote`, `--with-github` before relying on `gh`, and combine them when you need both.

### 2. Target Raspberry Pi runtime

Current core system packages and services expected by the active stack:

- `python3-venv`
- `mpv`
- `ffmpeg`
- `liblinphone-dev`
- `pkg-config`
- `cmake`
- `alsa-utils`
- `i2c-tools`
- `pisugar-server` running on PiSugar-based targets

Current repo-owned bootstrap baseline:

```bash
uv run yoyopod setup pi
```

This bootstraps the baseline package/build contract only. It does not yet solve
cloud voice credential provisioning, board/modem permissions, or non-Debian portability.
On the Pi, this flow now creates or refreshes the repo checkout `.venv` with
`python3 -m venv` and `pip install -e '.[dev]'`, so the board does not need
`uv` installed locally.

Feature extras are opt-in:

- `yoyopod setup pi --with-voice`
- `yoyopod setup pi --with-network`
- `yoyopod setup pi --with-pisugar`

Current repo-owned verification baseline:

```bash
uv run yoyopod setup verify-pi
```

This verifies presence and basic build state. It does not perform deeper
artifact health checks for every native/runtime dependency. The current baseline
checks the tracked config files, `python3`, the checkout venv Python, required
apt packages, and the built native runtime artifacts.

Use flags that match the actual target you are bringing up:

```bash
uv run yoyopod setup pi --with-pisugar
uv run yoyopod setup verify-pi --with-pisugar
```

Add `--with-voice` and/or `--with-network` when the target depends on the TTS or modem paths. `--with-pisugar` is the normal Whisplay/PiSugar hardware path because it adds the `pisugar-server` package and service check.

### 3. Feature-gated or hardware-specific extras

These are not universal for every contributor machine, but the repo should still name them explicitly when a feature depends on them.

#### Voice path

- cloud voice worker binary built from `workers/voice/go/`
- provider credentials supplied outside tracked config

#### Cellular / GPS path

- `ppp` for the modem PPP data path
- board- and modem-specific serial/device access

#### Board bringup variants

See:

- `docs/hardware/CUBIE_A7Z_BRINGUP.md`

## Repo-owned configuration contract

Tracked config lives in:

- `config/app/core.yaml`
- `config/audio/music.yaml`
- `config/device/hardware.yaml`
- `config/power/backend.yaml`
- `config/network/cellular.yaml`
- `config/voice/assistant.yaml`
- `config/communication/calling.yaml`
- `config/communication/messaging.yaml`
- `config/communication/calling.secrets.example.yaml`
- `config/communication/integrations/liblinphone_factory.conf`
- `config/people/directory.yaml`
- `config/people/contacts.seed.yaml`
- `deploy/pi-deploy.yaml`

Gitignored local overrides belong in:

- `config/communication/calling.secrets.yaml`
- `deploy/pi-deploy.local.yaml`

The tracked deploy contract must stay generic:

- no personal hostnames
- no personal usernames
- no secrets
- no machine-specific absolute paths unless they are intended defaults

## Current bringup contract

### Local developer bringup baseline

```bash
uv run yoyopod setup host
uv run yoyopod setup verify-host
cargo run --manifest-path device/Cargo.toml -p yoyopod-runtime -- --config-dir config --dry-run
cargo test --manifest-path device/Cargo.toml --workspace --locked
```

This is the minimum executable contract for contributors. Feature assets and
hardware-specific extras still need follow-through when the feature requires them.

### Target Pi bringup baseline

```bash
uv run yoyopod setup pi --with-pisugar
uv run yoyopod setup verify-pi --with-pisugar
yoyopod pi validate deploy
yoyopod pi validate smoke
yoyopod pi validate smoke --with-power --with-rtc
/opt/yoyopod-dev/checkout/device/runtime/build/yoyopod-runtime --config-dir /opt/yoyopod-dev/checkout/config --hardware whisplay
```

This does not yet provision external credentials or encode every
board/modem-specific permission step. Add `--with-voice` and/or `--with-network`
when the target needs those feature paths.

### Remote Pi workflow baseline

```bash
uv run yoyopod setup verify-host --with-remote-tools
yoyopod remote config edit
uv run yoyopod remote setup --with-pisugar
uv run yoyopod remote verify-setup --with-pisugar
yoyopod remote status
yoyopod remote validate --branch <branch> --sha <commit> --with-music --with-voip
```

These remote helpers mirror the same baseline contract. They still rely on
feature-specific follow-up for assets and unusual hardware bringup. Add
`--with-voice` and/or `--with-network` to the setup commands when the target
needs those feature paths. They now invoke the checkout-local `.venv/bin/python`
instead of requiring `uv` on the board.

## Verification before blaming product code

Before treating a failure as an app bug, verify the setup layer first.

Checklist:

- local bootstrap completes with `uv run yoyopod setup host`
- local verification passes with `uv run yoyopod setup verify-host`
- remote Pi workflows use `uv run yoyopod setup verify-host --with-remote-tools`
- GitHub CLI workflows use `uv run yoyopod setup verify-host --with-github`
- tracked config files are present under `config/`
- required system packages are verified with `uv run yoyopod setup verify-pi`
- target feature extras are verified with the matching `--with-pisugar`, `--with-voice`, and `--with-network` flags
- native artifacts have been built when the feature requires them
- `yoyopod pi validate smoke` passes for the requested hardware path
- remote config values come from `deploy/pi-deploy.yaml` plus local overrides, not tribal knowledge

## Current gaps

This repo is still missing some setup hardening that a foundation-grade repo should have:

- provisioning of external voice provider credentials
- board- and modem-specific device-permission setup for every bringup variant
- portability beyond the current Debian-based Raspberry Pi package flow

The contract is now executable, but those remaining edges are still real.
