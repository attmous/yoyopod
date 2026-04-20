# Deploy Workflow

Applies to: `deploy/pi-deploy.yaml`, `yoyopod remote`, Raspberry Pi validation, and Pi-facing agent skills

## Default Contract

The normal target-hardware workflow validates committed code only.

Use this order:

1. finish implementation locally
2. run local checks as needed
3. commit the intended changes
4. push the branch
5. deploy the committed branch and preferably the exact commit SHA to the Raspberry Pi
6. run smoke validation
7. launch or restart the app
8. verify startup with the PID file, startup marker, and recent logs
9. leave the app running for manual testing

The repo-owned command for that flow is:

```bash
git branch --show-current
git rev-parse HEAD
yoyopod remote validate --branch <branch> --sha <commit> --with-music --with-voip --with-navigation
```

`yoyopod remote validate` is the default because it:

- stops on uncommitted local changes
- requires a pushed branch/SHA
- syncs one stable checkout path on the board
- runs the target-side deploy, smoke, and requested service/stability checks before launch
- waits for the startup marker after restart
- prints recent logs and leaves the app running

## Stable Pi Checkout Path

The board must reuse one stable checkout path, configured by `project_dir` in `deploy/pi-deploy.yaml`.

Why this is the normal contract:

- dependency installs are expensive on Pi Zero hardware
- native LVGL and Liblinphone rebuilds can be expensive
- repeated fresh copies waste time and introduce drift
- the fixed path is what the service unit, logs, PID file, and agent skills expect

Do not normalize ad hoc per-branch directories on the board.

## Command Map

The `rpi-deploy` Claude Code plugin is still the high-level integration surface, but in this repo `yoyopod remote` is the executable implementation and the skills should stay thin wrappers around it.

| Command | Purpose |
|---|---|
| `/yoyopod-deploy` | Commit-safe branch/SHA validation on the Pi |
| `/yoyopod-sync` | Rare-case dirty-tree rsync escape hatch for debugging only |
| `/yoyopod-logs [N] [--errors] [--filter <sub>]` | Tail app logs from the Pi |
| `/yoyopod-restart` | Restart the already-synced app |
| `/yoyopod-status` | Health check dashboard |
| `/yoyopod-screenshot [--readback]` | Capture display output as PNG |
Lower-level `yoyopod remote` commands:

- `yoyopod remote validate` is the default branch/SHA validation flow (use `--with-navigation` for the navigation soak, `--with-lvgl-soak` for the LVGL soak)
- `yoyopod remote sync` is the committed-code sync primitive
- `yoyopod remote restart` restarts the synced app and verifies startup

Target-side `yoyopod pi validate` commands:

- `yoyopod pi validate deploy` checks the deploy contract, config files, runtime paths, and entrypoints without launching the app
- `yoyopod pi validate smoke` checks environment, display, input, and optional PiSugar telemetry
- `yoyopod pi validate music` checks the mpv backend in isolation
- `yoyopod pi validate voip` checks Liblinphone startup and SIP registration in isolation
- `yoyopod pi validate navigation` runs the one-button navigation, idle, and playback stress path used for freeze repro
- `yoyopod pi validate stability` runs the repeated LVGL transition and sleep/wake stability pass

Config lives in `deploy/pi-deploy.yaml` plus optional `deploy/pi-deploy.local.yaml` for machine-specific host and user overrides. Preferred edit flow:

```bash
yoyopod remote config show
yoyopod remote config edit
uv run yoyopod remote setup
uv run yoyopod remote verify-setup
```

## Escape Hatch Only

Dirty-tree deploys are still allowed as a rare debugging override, but they are not the default validation story.

Use `yoyopod remote sync` with caution for dirty-tree debugging only when:

- the user explicitly asks to validate uncommitted local state
- you are doing one-off hardware debugging and have called out that the Pi is not running committed code

Do not present dirty-tree sync as the normal way to validate a branch or PR.

## Target Hardware

- Raspberry Pi Zero 2W (416 MB RAM)
- SSH host, user, and stable project-dir defaults come from `deploy/pi-deploy.yaml` plus gitignored `deploy/pi-deploy.local.yaml`
- Machine-local hostnames, usernames, and path overrides must stay out of tracked files
- Default project dir on Pi: `/home/pi/YoyoPod_Core`
- Default venv on Pi: `/home/pi/YoyoPod_Core/.venv`
