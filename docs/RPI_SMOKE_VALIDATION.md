# Raspberry Pi Smoke Validation

This guide separates the validation work that is safe in CI from the checks that still require Raspberry Pi hardware, Mopidy, and a reachable SIP account.

## Validation Layers

### 1. CI-safe Python checks

Run these anywhere:

```bash
uv sync --extra dev
uv run pytest -q
```

This covers the pure-Python and simulation-mode regression suite.

### 2. Raspberry Pi core hardware smoke

Run this on the target Raspberry Pi after pulling the latest branch:

```bash
uv run python scripts/pi_smoke.py
```

What it checks:

- target environment information
- display initialization on real hardware
- matching input adapter construction and start/stop

Expected result:

- `display` should report a real hardware adapter, not simulation
- `input` should report semantic capabilities for the attached hardware

### 3. Raspberry Pi service smoke

Add Mopidy and SIP checks when the services are expected to be available:

```bash
uv run python scripts/pi_smoke.py --with-mopidy --with-voip
```

What it checks:

- Mopidy JSON-RPC connectivity using `config/yoyopod_config.yaml`
- `linphonec` startup and SIP registration using `config/voip_config.yaml`

Useful flags:

- `--mopidy-timeout 10`
- `--voip-timeout 15`
- `--verbose`

## Manual Follow-up Checks

### Full application startup

```bash
uv run python yoyopod.py
```

Verify:

- the home/menu UI renders on the target display
- button input navigates screens correctly
- the app returns cleanly on `Ctrl+C`

### VoIP registration drill

```bash
uv run python scripts/check_voip_registration.py
```

Use this when you want a registration-only pass with detailed logs.

### Incoming call debug drill

```bash
uv run python scripts/debug_incoming_call.py
```

Use this when SIP registration works but incoming-call parsing or callback delivery looks wrong.

### Whisplay display-only debug

```bash
uv run python test_hal_whisplay.py
```

Use this only on a Pi with the Whisplay hardware attached. It is a manual hardware smoke script, not part of CI.

## Suggested Order On Hardware

1. `uv sync --extra dev`
2. `uv run pytest -q`
3. `uv run python scripts/pi_smoke.py`
4. `uv run python scripts/pi_smoke.py --with-mopidy --with-voip`
5. `uv run python yoyopod.py`

## Failure Triage

- `display` fails: check attached HAT, driver/library install, and `display.hardware` config
- `input` fails: check the matching display adapter initialized correctly first
- `mopidy` fails: verify Mopidy is running and reachable at the configured host/port
- `voip` fails: verify `linphonec`, SIP credentials, network reachability, and audio device configuration

## Notes

- The smoke script exits non-zero if any requested check fails.
- CI intentionally does not run hardware-in-the-loop checks.
- The hardware smoke script is meant to be quick. Use the manual drills above when you need deeper debugging.
