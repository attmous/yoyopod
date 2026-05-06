# Development Guide

This guide holds the operational detail that does not belong on the repo landing page.

If you are new here, read these first:

1. [`../README.md`](../../README.md)
2. [`README.md`](../README.md)
3. [`CONTRIBUTOR_WORKFLOW.md`](CONTRIBUTOR_WORKFLOW.md)
4. [`SYSTEM_ARCHITECTURE.md`](../architecture/SYSTEM_ARCHITECTURE.md)

## Source of truth

For current behavior, trust:
- current Rust runtime and host code in `device/`
- current operations tooling in `yoyopod_cli/`
- this guide for setup and workflow
- [`SYSTEM_ARCHITECTURE.md`](../architecture/SYSTEM_ARCHITECTURE.md) for runtime topology
- [`../AGENTS.md`](../../AGENTS.md) and `rules/` for repo guidance

Treat plan docs and checklists as supporting context unless they explicitly state they are current.

## Python Environment

```bash
uv run yoyopod setup host
uv run yoyopod setup verify-host
```

These commands define the baseline executable setup contract. They do not yet
cover external service credentials or every board/modem-specific setup edge.
If `yoyopod` reports that the contributor CLI dependencies are missing, run
`uv sync --extra dev` and retry.

If you plan to use the remote Pi workflow from your dev machine, verify the
extra host tools explicitly:

```bash
uv run yoyopod setup verify-host --with-remote-tools
```

If you plan to use GitHub CLI helpers for branch or PR work, verify that too:

```bash
uv run yoyopod setup verify-host --with-github
```

Combine both flags when you need both surfaces.

## System Dependencies

The current repo-owned setup contract lives in [`SETUP_CONTRACT.md`](SETUP_CONTRACT.md).

Short version:

Core Raspberry Pi packages and services expected by the active stack:

- `mpv`
- `ffmpeg`
- `liblinphone-dev`
- `pkg-config`
- `cmake`
- `alsa-utils`
- `i2c-tools`
- `pisugar-server` on PiSugar-based targets

Feature-gated extras are documented there too, including:

- `ppp` for the modem PPP path

Example:

```bash
uv run yoyopod setup pi --with-pisugar
uv run yoyopod setup verify-pi --with-pisugar
```

Treat those commands as the baseline package/build verifier, not proof that all
feature assets and hardware-specific setup are complete.

Add `--with-voice` and/or `--with-network` when the target uses the TTS or modem paths. For PiSugar-based hardware, `--with-pisugar` is what makes `pisugar-server` part of the verified contract.

## Configuration

Tracked config files live under `config/`:

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

Key settings:

- `config/app/core.yaml`
  - `app.*`, `ui.*`, `logging.*`, `diagnostics.*`
- `config/audio/music.yaml`
  - `audio.music_dir`, `audio.recent_tracks_file`, `audio.mpv_*`, `audio.default_volume`
- `config/device/hardware.yaml`
  - `input.*`, `display.*`, `communication_audio.*`, `media_audio.*`, `voice_audio.*`
- `config/power/backend.yaml`
  - `power.*` PiSugar backend transport, watchdog, polling, warning, and shutdown policy
- `config/network/cellular.yaml`
  - `network.*` cellular modem enablement, ports, APN, GPS, and PPP timeout
- `config/voice/assistant.yaml`
  - `assistant.*` voice commands, cloud-worker STT/TTS, prompt policy, and command routing
- `config/communication/calling.yaml`
  - SIP identity, transport, STUN, call policy, call-history path
- `config/communication/messaging.yaml`
  - file transfer, message-store paths, voice-note policy
- `config/people/directory.yaml`
  - paths for mutable people data under `data/people/`

Local SIP credentials belong in `config/communication/calling.secrets.yaml` or
env vars. Mutable contacts live in `data/people/contacts.yaml`, optionally
bootstrapped from `config/people/contacts.seed.yaml`. Mutable media history
lives in `data/media/recent_tracks.json`.

Current approved-contacts behavior:

- contacts may include both `sip_address` and `phone_number`
- the runtime prefers SIP for calling while GSM remains disabled
- backend config sync can replace the cloud-managed subset while preserving
  local-only contacts
- a claimed device may upload prestored local contacts once when backend
  authority is still empty for that household

## Running

Rust runtime dry run:

```bash
cargo run --manifest-path device/Cargo.toml -p yoyopod-runtime -- --config-dir config --dry-run
```

Rust runtime:

```bash
device/runtime/build/yoyopod-runtime --config-dir config
```

Installed console entrypoint:

```bash
yoyopod
```

The installed `yoyopod` command is the operations CLI. It does not launch the
app runtime.

Legacy Python runtime demos were moved under `legacy/python-runtime/demos/`.
They are retained only as historical reference and are not part of the active
Rust runtime workflow.

## Validation

Local validation:

```bash
cargo test --manifest-path device/Cargo.toml --workspace --locked
```

Run targeted Python checks only when Python CLI/deploy/compatibility files
change:

```bash
uv run pytest -q tests/cli tests/deploy
```

Optional extra syntax/import smoke for broad Python tree changes:

```bash
python -m compileall yoyopod_cli tests scripts
```

Full quality audit of the current repo debt:

```bash
uv run python scripts/quality.py audit
```

The staged gate contract and exact target set live in [`QUALITY_GATES.md`](QUALITY_GATES.md).

Profiling and bounded branch-to-branch benchmarks:

```bash
uv run yoyopod dev profile tools
uv run yoyopod dev profile targets
uv run yoyopod dev profile cprofile --target simulate-bootstrap
uv run yoyopod dev profile pyinstrument --target simulate-loop --iterations 300 --html
uv run yoyopod dev profile pyperf --target scaffold-loop --fast
```

For the full Pi-focused profiling path, including `py-spy`, `perf`, and the
repo's coordinator-loop diagnostics, see [`PI_PROFILING_WORKFLOW.md`](PI_PROFILING_WORKFLOW.md).

Target-side validation suite:

```bash
yoyopod pi validate deploy
yoyopod pi validate smoke
yoyopod pi validate smoke --with-power --with-rtc
yoyopod pi validate music
yoyopod pi validate voip
yoyopod pi validate navigation
yoyopod pi validate stability
```

## Raspberry Pi Workflow

Preferred remote helper:

```bash
uv run yoyopod setup verify-host --with-remote-tools
yoyopod remote config edit
uv run yoyopod remote setup --with-pisugar
uv run yoyopod remote verify-setup --with-pisugar
yoyopod remote config show
yoyopod remote status
git branch --show-current
git rev-parse HEAD
yoyopod remote validate --branch <branch> --sha <commit> --with-music --with-voip --with-lvgl-soak
yoyopod remote validate --branch <branch> --sha <commit> --with-music --with-navigation
yoyopod remote preflight --branch <branch> --with-music --with-voip --with-navigation --with-lvgl-soak
yoyopod remote service status
yoyopod remote logs --lines 200
```

That remote flow mirrors the same baseline contract. You still need feature-specific
follow-through for external credentials and unusual board/modem bringup.
Add `--with-voice` and/or `--with-network` to the setup commands when the target depends on those paths.

If a GitHub fetch or push fails with a short-lived connectivity error, retry it
several times before treating it as a real failure. This environment has seen
brief `github.com` reachability blips.

The detailed deploy and validation flows live in:

- `docs/operations/PI_DEV_WORKFLOW.md`
- `docs/operations/RPI_SMOKE_VALIDATION.md`
- `rules/deploy.md`

## Logging

The app writes:

- `logs/yoyopod.log`
- `logs/yoyopod_errors.log`

Pi deploy defaults live in:

- `deploy/pi-deploy.yaml`
- `deploy/pi-deploy.local.yaml` for gitignored machine-local overrides

Useful remote log commands:

```bash
yoyopod remote logs --lines 200
yoyopod remote logs --errors
yoyopod remote logs --filter comm
yoyopod remote logs --follow --filter ERROR
```

## Package Layout

```text
device/
  runtime/
  protocol/
  worker/
  harness/
  cloud/
  media/
  network/
  power/
  speech/
  ui/
  voip/
yoyopod_cli/
  main.py
  pi/
  config/
  contracts/
scripts/
  quality.py
legacy/
  python-runtime/
```

## Current Active Docs

Start with [`README.md`](../README.md) for the full docs map.

Current contributor, runtime, and setup docs:
- `docs/operations/CONTRIBUTOR_WORKFLOW.md`
- `docs/operations/QUALITY_GATES.md`
- `docs/operations/SETUP_CONTRACT.md`
- `docs/architecture/SYSTEM_ARCHITECTURE.md`
- `docs/hardware/POWER_MODULE.md`
- `docs/features/LOCAL_FIRST_MUSIC_PLAN.md`
- `docs/features/MPV_DEPENDENCIES.md`
- `docs/operations/PI_DEV_WORKFLOW.md`
- `docs/operations/RPI_SMOKE_VALIDATION.md`

Plan and migration docs can still be useful, but they are not automatically the source of truth.

Historical milestone notes are archived under `docs/archive/`.
