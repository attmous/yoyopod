# Raspberry Pi Smoke Validation

This guide separates CI-safe checks from the target-hardware checks that still require a Raspberry Pi, the mpv music backend, and a reachable SIP account.

The default board-validation path from the dev machine is now committed-code validation through `yoyoctl remote validate`.

## Validation Layers

### 1. CI-safe Python checks

Run these anywhere:

```bash
uv sync --extra dev
uv run pytest -q
```

This covers the pure-Python and simulation-mode regression suite.

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
- the requested smoke checks pass
- the app restarts cleanly
- the PID file and startup marker agree
- recent logs look sane before handoff

Expected result:

- the app stays running on the Pi after validation
- the Pi reflects the requested committed branch/SHA, not dirty local state
- the startup marker matches the active PID

### 3. On-Pi core hardware smoke

Run these directly on the target Raspberry Pi when you want the lower-level hardware checks without the remote orchestration layer:

```bash
yoyoctl pi smoke
yoyoctl pi smoke --with-power --with-rtc
yoyoctl pi lvgl soak
```

What it checks:

- target environment information
- display initialization on real hardware
- matching input adapter construction and start/stop
- optional LVGL transition and sleep/wake soak when requested

Expected result:

- `display` reports a real hardware adapter, not simulation
- `input` reports the active interaction profile plus semantic capabilities for the attached hardware

### 4. On-Pi service smoke

Add music-backend and SIP checks when those services are expected to be available:

```bash
yoyoctl pi smoke --with-music --with-voip
yoyoctl pi smoke --with-power --with-rtc --with-music --with-voip
```

What it checks:

- PiSugar battery telemetry and RTC state when requested
- mpv music-backend startup using `config/yoyopod_config.yaml`
- Liblinphone startup and SIP registration using `config/voip_config.yaml`
- Liblinphone media and codec defaults from `config/liblinphone_factory.conf`

Useful flags:

- `--music-timeout 10`
- `--voip-timeout 15`
- `--verbose`

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
2. `uv run pytest -q`
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

- `display` fails: check attached HAT, driver and library install, and `display.hardware` config
- `input` fails: check the matching display adapter initialized correctly first
- `music` fails: verify `mpv` is installed, the configured socket path is writable, and the configured `audio.music_dir` exists
- `voip` fails: verify the Liblinphone shim build, `config/liblinphone_factory.conf`, SIP credentials, network reachability, and audio device configuration
- `validate` fails before launch: check whether the branch was actually pushed and whether the Pi checkout is reachable over SSH

## Notes

- the smoke script exits non-zero if any requested check fails
- CI intentionally does not run hardware-in-the-loop checks
- `yoyoctl remote validate` is the normal branch and PR validation path
- the hardware smoke script is meant to be quick; use the manual drills above when you need deeper debugging
