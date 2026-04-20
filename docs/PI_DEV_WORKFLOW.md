# Raspberry Pi Dev Workflow

This guide covers the normal dev-machine-to-board loop for YoyoPod.

The default contract is:

1. finish the implementation locally
2. commit the intended changes
3. push the branch
4. validate that committed branch and exact SHA on the Pi
5. leave the app running for manual hardware testing

Dirty-tree sync still exists, but only as a rare debugging override.

## Stable Board Checkout

The Raspberry Pi should reuse one stable checkout path, configured by `project_dir` in `deploy/pi-deploy.yaml`.

Why this is the default:

- `uv sync` is expensive on Pi Zero hardware
- native LVGL and Liblinphone rebuilds can be expensive
- repeated fresh copies waste time
- the service unit, logs, PID file, and restart flow all assume one stable path

Do not normalize ad hoc per-branch checkout directories on the board.

## Setup

Make sure your dev machine can SSH into the Raspberry Pi with an alias or reachable host name.

Before the first `yoyopod remote validate`, verify the host prerequisites that the remote workflow depends on:

```bash
uv run yoyopod setup verify-host --with-remote-tools
```

If you also use GitHub CLI helpers for branch or PR work, verify that separately:

```bash
uv run yoyopod setup verify-host --with-github
```

The repo-tracked deploy contract lives in `deploy/pi-deploy.yaml`.

- keep `host` and `user` blank there
- keep the shared `project_dir` stable there
- put machine-specific values in `deploy/pi-deploy.local.yaml`
- create or update that file with:

```bash
yoyopod remote config edit
```

Bootstrap and verify the target with flags that match the hardware and feature paths you actually expect:

```bash
uv run yoyopod remote setup --with-pisugar
uv run yoyopod remote verify-setup --with-pisugar
```

Add `--with-voice` and/or `--with-network` when the target needs the TTS or modem paths. `--with-pisugar` is the normal Whisplay and PiSugar path because it pulls in the `pisugar-server` package and service check.

Examples:

```bash
ssh rpi-zero
ssh tifo@192.168.1.42
```

Optional environment defaults:

```bash
export YOYOPOD_PI_HOST=rpi-zero
export YOYOPOD_PI_PROJECT_DIR=~/YoyoPod_Core
```

On Windows PowerShell:

```powershell
$env:YOYOPOD_PI_HOST="rpi-zero"
$env:YOYOPOD_PI_PROJECT_DIR="~/YoyoPod_Core"
```

If your actual deployed board uses a different stable checkout path, set that in
your local override instead of assuming the repo default. For example, the live
`piz` board in this environment uses `~/yoyo-py`.

## Default Validate-On-Board Flow

Use this when validating a feature branch or PR on target hardware.

1. Confirm the local tree is committed:
   ```bash
   git status --short
   ```
2. Resolve the branch and exact commit:
   ```bash
   git branch --show-current
   git rev-parse HEAD
   ```
3. Push the branch:
   ```bash
   git push
   ```
   If the branch has no upstream yet:
   ```bash
   git push -u origin <branch>
   ```
   If `github.com` is briefly unreachable, do not treat one short network error
   as a definitive failure. Retry the push a few times before escalating.
4. Run the repo-owned hardware validation flow:
   ```bash
   yoyopod remote validate --branch <branch> --sha <commit>
   ```

Useful variations:

```bash
yoyopod remote validate --branch <branch> --sha <commit> --with-music --with-voip
yoyopod remote validate --branch <branch> --sha <commit> --with-power --with-rtc
yoyopod remote validate --branch <branch> --sha <commit> --with-navigation
yoyopod remote validate --branch <branch> --sha <commit> --with-music --with-navigation
yoyopod remote validate --branch <branch> --sha <commit> --with-lvgl-soak
yoyopod remote validate --branch <branch> --sha <commit> --skip-uv-sync
```

When `--with-music` is enabled, the Pi-side smoke flow seeds the deterministic validation library into the configured `test_music_target_dir` before it exercises the music backend.

The seeded validation library is explicit and stable:

- `yoyopod-validation-set.m3u`
- `tracks/alpha-beacon.wav`
- `tracks/bravo-lantern.wav`
- `tracks/charlie-sundial.wav`

`yoyopod remote validate` does all of this:

1. stops if the local worktree is dirty
2. verifies the requested branch is pushed
3. syncs the stable Pi checkout to the branch and exact SHA
4. runs `uv sync --extra dev` unless skipped
5. runs `yoyopod pi validate deploy`
6. runs the requested target-side validation checks
7. restarts the app
8. verifies startup with the PID file and startup marker
9. prints the latest startup marker and recent logs
10. leaves the app running for manual testing

## Lower-Level Commands

### Check remote status

```bash
yoyopod remote status
```

Shows:

- remote branch or `DETACHED`
- remote commit
- dirty working tree state on the Pi checkout
- music backend process state
- tracked PID file state
- latest startup marker from the file log
- top memory processes

### Sync committed code without launching the app

```bash
yoyopod remote sync --branch <branch>
yoyopod remote sync --branch <branch> --sha <commit>
```

Use this when you want the stable checkout updated but do not want the full validate flow yet.

### Run validation

```bash
yoyopod remote validate --branch <branch> --sha <commit>
yoyopod remote validate --branch <branch> --sha <commit> --with-power --with-rtc
yoyopod remote validate --branch <branch> --sha <commit> --with-music --with-voip --with-rtc
yoyopod remote validate --branch <branch> --sha <commit> --with-navigation
yoyopod remote validate --branch <branch> --sha <commit> --with-lvgl-soak
```

This composes the target-side suite:

- `yoyopod pi validate smoke`
- `yoyopod pi validate music`
- `yoyopod pi validate voip`
- `yoyopod pi validate navigation`
- `yoyopod pi validate stability`

### Restart the already-synced app

```bash
yoyopod remote restart
```

This waits for the startup marker and matching PID before returning success.

### Structured file logs

```bash
yoyopod remote logs --lines 200
yoyopod remote logs --errors
yoyopod remote logs --filter comm
yoyopod remote logs --filter coord
yoyopod remote logs --follow --filter ERROR
```

This tails the file sinks declared in `deploy/pi-deploy.yaml`, which is the stable Pi contract for:

- `<project-dir>/logs/yoyopod.log`
- `<project-dir>/logs/yoyopod_errors.log`
- `/tmp/yoyopod.pid`

For keep-alive freeze triage, watch the `comm` and `coord` lines together:

- `VoIP timing window`: rolling summary of keep-alive schedule delay, iterate duration, and the worst loop gap in that window
- `VoIP iterate timing drift`: one-off warning when a keep-alive step ran late or took unusually long
- `Runtime loop blocked`: one-off warning when some other coordinator work starved the loop enough to threaten VoIP cadence

### Freeze investigation

When the app looks stuck during idle navigation, use the screenshot signal path as the first
evidence trigger:

```bash
yoyopod remote logs --follow --filter ERROR
yoyopod remote screenshot --readback
```

What to expect:

- `yoyopod remote screenshot --readback` sends `SIGUSR1` to the app.
- `SIGUSR1` now does two things:
  - appends an all-thread traceback dump to `logs/yoyopod_errors.log`
  - logs a structured runtime snapshot before trying the queued screenshot capture
- recent runtime logs also expose VoIP keep-alive timing in three layers:
  - `VoIP keep-alive native iterate slow` means the Liblinphone keep-alive call itself blocked
  - `VoIP iterate timing drift` means the coordinator reached keep-alive late or the full iterate pass ran long
  - `Coordinator blocking span` points at nearby coordinator work that may have delayed keep-alives
- the periodic `VoIP timing window` summary rolls those samples up for hardware runs without logging every 20 ms iterate
- if the main loop is still healthy enough, you also get the PNG
- if the main loop is wedged and the PNG never appears, the error log is still the first place to inspect

For shadow-buffer comparison, use:

```bash
yoyopod remote screenshot
```

That uses `SIGUSR2`, which captures the same traceback + runtime evidence but prefers the legacy
shadow-first screenshot path.

### Automatic responsiveness watchdog

For validation runs where you want the app to capture evidence on its own, enable the
opt-in responsiveness watchdog in `config/app/core.yaml` or via env vars:

```yaml
diagnostics:
  responsiveness_watchdog_enabled: true
  responsiveness_stall_threshold_seconds: 5.0
```

What it does:

- watches `loop_heartbeat_age_seconds` in the running app status
- captures one evidence bundle when the coordinator loop stops advancing past the threshold
- writes:
  - `logs/responsiveness/<timestamp>-<reason>.json`
  - `logs/responsiveness/<timestamp>-<reason>.traceback.txt`
- logs one summary line to `logs/yoyopod_errors.log` pointing at those artifacts

How to interpret the extra status markers in the JSON bundle:

- `input_activity_age_seconds`: raw or semantic input activity seen by the input side
- `handled_input_activity_age_seconds`: last input activity the coordinator actually drained
- `last_input_action` / `last_handled_input_action`: the latest action names on each side

If `input_activity_age_seconds` is fresh but `handled_input_activity_age_seconds` is stale, the
input side is still alive and the stall is likely between input delivery and the coordinator/UI
thread. If both are stale and `loop_heartbeat_age_seconds` is also stale, treat it as a broader
runtime stall.

### Production systemd service

```bash
yoyopod remote service status
yoyopod remote service install
yoyopod remote service restart
yoyopod remote service logs --lines 150
```

This installs `deploy/systemd/yoyopod@.service` onto the Pi as `yoyopod@<remote-user>.service`, enables it at boot, and records the merged `project_dir` in `/etc/default/yoyopod` so the service follows the same stable checkout path.

### PiSugar helpers

```bash
yoyopod remote rtc status
yoyopod remote power
```

## Preflight

`yoyopod remote preflight` is still useful, but it is a preparation step, not the full hardware-validation finish line.

```bash
yoyopod remote preflight --branch <branch> --with-music --with-voip --with-navigation --with-lvgl-soak
```

What it does:

1. runs local `compileall`
2. runs local `uv run pytest -q`
3. syncs the chosen branch to the Raspberry Pi
4. runs the Raspberry Pi smoke pass

Use it before commit when you want an extra sanity pass, or before `yoyopod remote validate` when you want a stricter gate.

## Dirty-Tree Escape Hatch

`yoyopod remote sync` is a debugging escape hatch and is not the normal validation path.

Use it only when:

- the user explicitly wants to validate uncommitted local changes
- you are doing a one-off debugging session and have called out that the Pi is not running committed code

Commands:

```bash
yoyopod remote sync
yoyopod remote sync --skip-restart
```

If you use it, say clearly that the board is running a dirty-tree override instead of the committed branch/SHA flow.

## Suggested Daily Loop

1. Run local checks as needed:
   ```bash
   uv run python scripts/quality.py ci
   ```
2. Commit the intended change.
3. Push the branch.
4. Resolve the exact commit:
   ```bash
   git rev-parse HEAD
   ```
5. Validate on the Pi:
   ```bash
   yoyopod remote validate --branch <branch> --sha <commit> --with-music --with-voip
   ```
6. Manually test on the target hardware while the app remains running.

When you are chasing idle freezes or routed-screen hangs, add the deterministic soak:

```bash
yoyopod remote validate --branch <branch> --sha <commit> --with-music --with-navigation
```

## Release / Pre-Merge Checklist

- local branch is green with `uv run python scripts/quality.py ci`
- branch is pushed and reviewed
- `yoyopod remote validate --branch <branch> --sha <commit> --with-music --with-voip --with-lvgl-soak` passes
- if you touched idle navigation, `yoyopod remote validate --branch <branch> --sha <commit> --with-music --with-navigation` passes
- the app starts cleanly and stays running for manual hardware testing
- manual sanity still passes for display, input, music, SIP registration, and call flow

## Notes

- `yoyopod remote validate` is the default board-validation contract for branches and PRs.
- `yoyopod remote preflight` is intentionally non-launching.
- `yoyopod remote service install` expects passwordless `sudo` or an interactive sudo policy on the Pi.
- `yoyopod remote sync` used as a dirty-tree override is a debugging escape hatch, not the normal deploy story.
- For deeper hardware debugging, use `docs/RPI_SMOKE_VALIDATION.md`.
