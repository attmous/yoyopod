# Raspberry Pi Smoke Validation

This guide separates CI-safe checks from the target-hardware checks that still require a Raspberry Pi, the mpv music backend, and a reachable SIP account.

The default board-validation path from the dev machine is now committed-code validation through `yoyopod remote validate`.

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
yoyopod remote validate --branch <branch> --sha <commit>
```

Useful variations:

```bash
yoyopod remote validate --branch <branch> --sha <commit> --with-power --with-rtc
yoyopod remote validate --branch <branch> --sha <commit> --with-music --with-voip
yoyopod remote validate --branch <branch> --sha <commit> --with-navigation
yoyopod remote validate --branch <branch> --sha <commit> --with-music --with-navigation
yoyopod remote validate --branch <branch> --sha <commit> --with-music --with-voip --with-lvgl-soak
```

When `--with-music` is enabled, the Pi smoke flow provisions a deterministic validation library under the configured `test_music_target_dir` before the mpv checks run.

The seeded validation library is explicit and stable:

- `yoyopod-validation-set.m3u`
- `tracks/alpha-beacon.wav`
- `tracks/bravo-lantern.wav`
- `tracks/charlie-sundial.wav`

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
yoyopod pi validate deploy
yoyopod pi validate smoke
yoyopod pi validate smoke --with-power --with-rtc
yoyopod pi validate music
yoyopod pi validate voip
yoyopod pi validate navigation
yoyopod pi validate stability
```

What each command checks:

- `deploy`: deploy contract files, tracked runtime config, runtime path parents, and app entrypoints without launching the app
- `smoke`: target environment, display initialization on real hardware, matching input adapter construction and start/stop, plus optional PiSugar power and RTC checks
- `music`: mpv music-backend startup using the composed `config/app|audio|device` topology
- `voip`: quick Liblinphone startup and SIP registration smoke using `config/communication/calling.yaml` plus local secrets/env
- `navigation`: repeatable one-button routed navigation with explicit idle dwells, click-driven transitions, optional playlist/shuffle playback, and a final sleep/wake pass
- `stability`: repeated LVGL transition plus sleep/wake recovery on the active app path

Useful flags:

- `yoyopod pi validate music --timeout 10`
- `yoyopod pi validate music --test-music-dir ~/YoYoPod_Test_Music`
- `yoyopod pi validate voip --timeout 15`
- `yoyopod pi validate navigation --with-playback --test-music-dir ~/YoYoPod_Test_Music`
- `yoyopod pi validate navigation --cycles 3 --idle-seconds 5 --tail-idle-seconds 20`
- `yoyopod remote validate --branch <branch> --sha <commit> --with-navigation`
- `yoyopod pi validate stability --cycles 3 --hold-seconds 0.3`
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
yoyopod pi voip check
```

Use this when you want a registration-only pass with detailed logs.

### VoIP reliability drills

These are the deeper real-hardware VoIP checks. They intentionally stay as a few focused commands instead of one giant wrapper, and each run writes a timestamped artifact bundle under `logs/voip-validation/` by default:

- `summary.json` — pass/fail, timings, final status, and the exact thresholds used
- `timeline.jsonl` — state changes, periodic status samples, and any network drop/restore hook results

Use them after `yoyopod pi validate voip` passes, not instead of it.

#### Registration stability

```bash
yoyopod pi validate voip --soak registration
yoyopod pi validate voip --soak registration --hold-seconds 120
```

What it proves:

- SIP registration reached `ok`
- SIP registration stayed `ok` for the requested hold window instead of flapping immediately after startup

Fail the run if registration never reaches `ok` or if it leaves `ok` during the hold.

#### Reconnect drill

```bash
yoyopod pi validate voip --soak reconnect
yoyopod pi validate voip --soak reconnect --disconnect-seconds 12
```

If you can automate the outage on the Pi, keep it explicit. The drill executes `--drop-command` and `--restore-command` with a shell, so treat them as trusted operator input for your own device only:

```bash
yoyopod pi validate voip --soak reconnect \
  --drop-command "nmcli networking off" \
  --restore-command "nmcli networking on"
```

What it proves:

- the manager reached `ok` before the outage
- registration actually left `ok` during the wobble or temporary loss
- registration returned to `ok` within the recovery timeout

Fail the run if the drill never sees registration leave `ok` or if recovery does not happen. That usually means the outage was too mild to prove reconnect behavior, or the backend failed to recover honestly.

#### Call soak

```bash
yoyopod pi validate voip --soak call --target sip:echo@example.com
yoyopod pi validate voip --soak call --target sip:echo@example.com --soak-seconds 900
```

Use a target that will actually answer, such as an echo bot or a second endpoint you control.

What it proves:

- registration reached `ok`
- the outbound call connected
- the call stayed in a connected media state for the requested soak duration

Fail the run if the call never connects, if registration drops during the soak, or if the call leaves the connected media states before the soak finishes.

#### Reading the artifacts

- A passing reconnect drill should show an initial `registration=ok`, a later non-`ok` registration event during the outage, and then a final return to `registration=ok`.
- A passing call soak should show the expected connect transition followed by periodic connected samples for the full soak duration.
- If a run fails, compare `summary.json` across runs first. It makes timing drift, last seen state, and the exact failure point obvious without reading the whole timeline.

When the full app is running, the coordinator-thread timing signals land in
`logs/yoyopod.log` and through `yoyopod remote logs --follow`.

- `VoIP iterate timing drift` is the per-keep-alive warning. `schedule_delay_ms` shows how late the iterate ran, `iterate_ms` shows how long the Liblinphone keep-alive took on the coordinator thread, and `native_events` shows how many backend events were drained during that pass.
- `VoIP timing window` is the low-frequency summary for target-hardware runs. Use it to spot repeated delay or duration spikes without reading every keep-alive warning. `max_blocking_span` and `max_blocking_span_ms` point at the worst nearby coordinator step seen in that summary window.
- `Runtime loop blocked` means the whole coordinator loop stalled between iterations.
- `Coordinator blocking span` names the specific runtime step that blocked long enough to threaten keep-alive cadence or UI responsiveness.
- `Runtime iteration slow` means the total loop iteration stayed on the coordinator thread too long even if the exact hot span was not obvious from a single callback.
- `runtime_cadence_mode`, `runtime_target_sleep_seconds`, `runtime_requested_sleep_seconds`, and `voip_effective_iterate_interval_seconds` in `app.get_status()` snapshots tell you whether the loop is in a fast interactive path, awake idle, or screen-off idle and what sleep / VoIP cadence it actually requested.
- Freeze snapshots also include `runtime_blocking_span_name`, `runtime_blocking_span_seconds`, and `runtime_blocking_span_age_seconds` so a `SIGUSR1` dump can tell you whether the last blocking span is still fresh or already stale.
- When `diagnostics.responsiveness_watchdog_enabled=true`, the app also writes automatic evidence bundles under `logs/responsiveness/` once the loop heartbeat stops advancing past the configured threshold.
- Those bundles include `input_activity_age_seconds` and `handled_input_activity_age_seconds` so you can tell whether input was still arriving while the coordinator/UI side stopped responding.

### Incoming call debug drill

```bash
yoyopod pi voip debug
```

Use this when SIP registration works but incoming-call parsing or callback delivery looks wrong.

### Whisplay display-only debug

```bash
yoyopod build lvgl
yoyopod pi validate lvgl
```

Use this only on a Pi with the Whisplay hardware attached. It validates the display/LVGL path without starting the full app and is not part of CI.

### Whisplay gesture tuning

This tooling (`pi tune`) was removed in the 2026-04 CLI polish. Use hardware-manual testing with the running app for gesture feel adjustment, or edit `config/device/hardware.yaml` timing overrides directly.

```bash
### LVGL Whisplay soak

```bash
yoyopod pi validate lvgl
yoyopod pi validate lvgl --cycles 3 --hold-seconds 0.3
```

Use this when Whisplay rendering feels fast but you still want a hardware pass for:

- repeated routed screen transitions
- sleep/wake recovery
- LVGL-only corruption or stuck redraw issues

### Navigation and idle stability soak

```bash
yoyopod pi validate navigation
yoyopod pi validate navigation --with-playback --test-music-dir ~/YoYoPod_Test_Music
yoyopod remote validate --branch <branch> --sha <commit> --with-navigation
```

Use this when you want a reproducible freeze-repro path that keeps the app mostly idle but still exercises:

- routed one-button navigation from the real input dispatcher
- click-driven transitions into `Listen`, `Talk`, `Ask`, and `Setup`
- playlist and shuffle playback navigation while mpv is active
- explicit idle dwell windows between actions
- a final tail-idle and sleep/wake pass on the hub

### PiSugar RTC drill

```bash
yoyopod pi power rtc status
yoyopod pi power rtc sync-to
```

Use this when you want a focused RTC read or sync pass without running the full app.

### PiSugar power drill

```bash
yoyopod pi power battery
```

Use this when you want a focused battery, charging, RTC, shutdown-threshold, and watchdog readout without the full smoke flow.

## Suggested Order On Hardware

1. `uv sync --extra dev`
2. `uv run python scripts/quality.py ci`
3. `git push`
4. `git rev-parse HEAD`
5. `yoyopod remote validate --branch <branch> --sha <commit> --with-music --with-voip`
6. manual follow-up on the still-running app

## Dirty-Tree Escape Hatch

`yoyopod remote sync` is a debugging escape hatch and is not the default validation contract.

Only use it when:

- you explicitly need to validate uncommitted local state
- you have called out that the board is not running committed branch/SHA code

## Failure Triage

- `deploy` fails: verify the checkout still has `deploy/pi-deploy.yaml`, `deploy/systemd/yoyopod-dev.service`, `deploy/systemd/yoyopod-prod.service`, the configured virtualenv, and writable runtime path parents
- `display` fails: check attached HAT, driver and library install, and `display.hardware` config
- `input` fails: check the matching display adapter initialized correctly first
- `music` fails: verify `mpv` is installed, the configured socket path is writable, and the provision target under `test_music_target_dir` is writable when deterministic seeding is enabled
- `voip` fails: verify the Liblinphone shim build, `config/communication/integrations/liblinphone_factory.conf`, SIP credentials, network reachability, and audio device configuration
- `voip --soak registration` fails: compare `logs/voip-validation/*/summary.json` across runs and look for whether startup never reached `ok` or whether `ok` flapped during the hold window
- `voip --soak reconnect` fails: check whether the run ever recorded a non-`ok` registration state, whether the outage lasted long enough to force a drop, and whether recovery returned before the timeout
- `voip --soak call` fails: check whether the target endpoint actually answered, whether registration stayed `ok`, and which non-connected call state ended the soak
- `navigation` fails: rerun `yoyopod pi validate navigation --verbose` or `yoyopod remote validate --with-navigation --verbose` and inspect which expected screen or playback transition stalled
- `stability` fails: rerun `yoyopod pi validate stability --verbose` or `yoyopod pi validate lvgl` for a deeper LVGL-only pass
- `validate` fails before launch: check whether the branch was actually pushed and whether the Pi checkout is reachable over SSH

## Notes

- each `yoyopod pi validate <command>` exits non-zero if its requested check fails
- CI intentionally does not run hardware-in-the-loop checks
- `yoyopod remote validate` is the normal branch and PR validation path
- the target validation suite is meant to stay small and composable; use the manual drills above when you need deeper debugging
