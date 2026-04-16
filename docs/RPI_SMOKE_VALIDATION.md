# Raspberry Pi Smoke Validation

This guide separates CI-safe checks from the target-hardware checks that still require a Raspberry Pi, the mpv music backend, and a reachable SIP account.

The default board-validation path from the dev machine is now committed-code validation through `yoyoctl remote validate`.

## Validation Layers

### 1. CI-safe Python checks

Run these anywhere:

```bash
uv sync --extra dev
uv run python scripts/quality.py ci
```

This mirrors the same staged gate plus pure-Python regression suite CI expects.

### 2. Default dev-machine-to-board validation

Use this for feature branches and PR validation on target hardware:

```bash
git status --short
git branch --show-current
git rev-parse HEAD
git push
yoyoctl remote validate --branch <branch> --sha <commit>
```

Useful variations:

```bash
yoyoctl remote validate --branch <branch> --sha <commit> --with-power --with-rtc
yoyoctl remote validate --branch <branch> --sha <commit> --with-music --with-voip
yoyoctl remote validate --branch <branch> --sha <commit> --with-music --with-voip --with-lvgl-soak
```

What it checks:

- the branch is committed locally
- the branch and exact SHA are pushed
- the stable Pi checkout is synced to committed code only
- the target-side deploy validation passes
- the requested target-side smoke, music, voip, and stability checks pass
- the app restarts cleanly
- the PID file and startup marker agree
- recent logs look sane before handoff

Expected result:

- the app stays running on the Pi after validation
- the Pi reflects the requested committed branch/SHA, not dirty local state
- the startup marker matches the active PID

### 3. On-Pi target validation suite

Run these directly on the target Raspberry Pi when you want focused, repeated-safe validation without the remote orchestration layer:

```bash
yoyoctl pi validate deploy
yoyoctl pi validate smoke
yoyoctl pi validate smoke --with-power --with-rtc
yoyoctl pi validate music
yoyoctl pi validate voip
yoyoctl pi validate stability
```

What each command checks:

- `deploy`: deploy contract files, tracked runtime config, runtime path parents, and app entrypoints without launching the app
- `smoke`: target environment, display initialization on real hardware, matching input adapter construction and start/stop, plus optional PiSugar power and RTC checks
- `music`: mpv music-backend startup using `config/yoyopod_config.yaml`
- `voip`: Liblinphone startup and SIP registration using `config/voip_config.yaml`
- `stability`: repeated LVGL transition plus sleep/wake recovery on the active app path

Useful flags:

- `yoyoctl pi validate music --timeout 10`
- `yoyoctl pi validate voip --timeout 15`
- `yoyoctl pi validate stability --cycles 3 --hold-seconds 0.3`
- `--verbose` on any suite command

## Manual Follow-Up Checks

### Full application startup on the Pi

```bash
uv run python yoyopod.py
```

Verify:

- the home and menu UI render on the target display
- button input navigates screens correctly
- the app returns cleanly on `Ctrl+C`

### VoIP registration drill

```bash
yoyoctl pi voip check
```

Use this when you want a registration-only pass with detailed logs.

When the full app is running, the coordinator-thread timing signals land in
`logs/yoyopod.log` and through `yoyoctl remote logs --follow`.

- `VoIP iterate timing drift` is the per-keep-alive warning. `schedule_delay_ms` shows how late the iterate ran, `iterate_ms` shows how long the Liblinphone keep-alive took on the coordinator thread, and `native_events` shows how many backend events were drained during that pass.
- `VoIP timing window` is the low-frequency summary for target-hardware runs. Use it to spot repeated delay or duration spikes without reading every keep-alive warning. `max_blocking_span` and `max_blocking_span_ms` point at the worst nearby coordinator step seen in that summary window.
- `Runtime loop blocked` means the whole coordinator loop stalled between iterations.
- `Coordinator blocking span` names the specific runtime step that blocked long enough to threaten keep-alive cadence or UI responsiveness.
- `Runtime iteration slow` means the total loop iteration stayed on the coordinator thread too long even if the exact hot span was not obvious from a single callback.
- Freeze snapshots also include `runtime_blocking_span_name`, `runtime_blocking_span_seconds`, and `runtime_blocking_span_age_seconds` so a `SIGUSR1` dump can tell you whether the last blocking span is still fresh or already stale.
- When `diagnostics.responsiveness_watchdog_enabled=true`, the app also writes automatic evidence bundles under `logs/responsiveness/` once the loop heartbeat stops advancing past the configured threshold.
- Those bundles include `input_activity_age_seconds` and `handled_input_activity_age_seconds` so you can tell whether input was still arriving while the coordinator/UI side stopped responding.

### Incoming call debug drill

```bash
yoyoctl pi voip debug
```

Use this when SIP registration works but incoming-call parsing or callback delivery looks wrong.

### Whisplay display-only debug

```bash
yoyoctl build lvgl
yoyoctl pi lvgl probe --scene carousel --duration-seconds 10
```

Use this only on a Pi with the Whisplay hardware attached. It validates the display/LVGL path without starting the full app and is not part of CI.

### Whisplay gesture tuning

```bash
yoyoctl pi tune
yoyoctl pi tune --double-tap-ms 240 --long-hold-ms 900
```

Use this when button feel needs tuning on the real device. It listens for the semantic Whisplay gestures, prints every detected `advance`, `select`, and `back` event with timing detail, and can apply temporary timing overrides without editing `config/yoyopod_config.yaml`.

Useful flags:

- `--duration-seconds 45`
- `--debounce-ms 75`
- `--double-tap-ms 240`
- `--long-hold-ms 900`
- `--verbose`

### LVGL Whisplay soak

```bash
yoyoctl pi lvgl soak
yoyoctl pi lvgl soak --cycles 3 --hold-seconds 0.3
```

Use this when Whisplay rendering feels fast but you still want a hardware pass for:

- repeated routed screen transitions
- sleep/wake recovery
- LVGL-only corruption or stuck redraw issues

### PiSugar RTC drill

```bash
yoyoctl pi power rtc status
yoyoctl pi power rtc sync-to
```

Use this when you want a focused RTC read or sync pass without running the full app.

### PiSugar power drill

```bash
yoyoctl pi power battery
```

Use this when you want a focused battery, charging, RTC, shutdown-threshold, and watchdog readout without the full smoke flow.

## Suggested Order On Hardware

1. `uv sync --extra dev`
2. `uv run python scripts/quality.py ci`
3. `git push`
4. `git rev-parse HEAD`
5. `yoyoctl remote validate --branch <branch> --sha <commit> --with-music --with-voip`
6. manual follow-up on the still-running app

## Dirty-Tree Escape Hatch

`yoyoctl remote rsync` still exists for rare debugging sessions, but it is not the default validation contract.

Only use it when:

- you explicitly need to validate uncommitted local state
- you have called out that the board is not running committed branch/SHA code

## Failure Triage

- `deploy` fails: verify the checkout still has `deploy/pi-deploy.yaml`, `deploy/systemd/yoyopod@.service`, the configured virtualenv, and writable runtime path parents
- `display` fails: check attached HAT, driver and library install, and `display.hardware` config
- `input` fails: check the matching display adapter initialized correctly first
- `music` fails: verify `mpv` is installed, the configured socket path is writable, and the configured `audio.music_dir` exists
- `voip` fails: verify the Liblinphone shim build, `config/liblinphone_factory.conf`, SIP credentials, network reachability, and audio device configuration
- `stability` fails: rerun `yoyoctl pi validate stability --verbose` or `yoyoctl pi lvgl soak` for a deeper LVGL-only pass
- `validate` fails before launch: check whether the branch was actually pushed and whether the Pi checkout is reachable over SSH

## Notes

- each `yoyoctl pi validate <command>` exits non-zero if its requested check fails
- CI intentionally does not run hardware-in-the-loop checks
- `yoyoctl remote validate` is the normal branch and PR validation path
- the target validation suite is meant to stay small and composable; use the manual drills above when you need deeper debugging
