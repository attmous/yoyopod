# Rust UI Host

The Rust UI Host is the Whisplay UI worker used by the Rust runtime. Rust owns
UI state, screen focus, one-button transitions, and Whisplay rendering when the
host is enabled or launched directly.

## Build

```bash
yoyopod build rust-ui-host
```

For host-only protocol tests:

```bash
yoyopod build rust-ui-host --no-hardware-feature
```

Direct native-LVGL builds require `YOYOPOD_LVGL_SOURCE_DIR` to point at an
LVGL 9.5 checkout.

CI builds the Whisplay host on a native Linux ARM64 runner with
`whisplay-hardware,native-lvgl` enabled and packages it with the other Rust
runtime binaries as:

```bash
yoyopod-rust-device-arm64-<exact-commit-sha>
```

For Raspberry Pi Zero 2W hardware validation, the deploy path is always:

1. Commit and push the branch.
2. Wait for the GitHub Actions `rust-device-arm64` job to pass for the exact commit.
3. Download and extract `yoyopod-rust-device-arm64-<sha>`.
4. Confirm it installed `device/ui/build/yoyopod-ui-host` on the Pi checkout.

Do not run `cargo build` or `yoyopod build rust-ui-host` on the Pi Zero 2W
unless the user explicitly overrides this rule. Local builds are for developer
workstations, CI, or faster ARM64 boards only.

## Required Whisplay Environment

The hardware backend reads explicit GPIO/SPI settings:

- `YOYOPOD_WHISPLAY_SPI_BUS`
- `YOYOPOD_WHISPLAY_SPI_CS`
- `YOYOPOD_WHISPLAY_SPI_HZ`
- `YOYOPOD_WHISPLAY_DC_GPIO`
- `YOYOPOD_WHISPLAY_RESET_GPIO`
- `YOYOPOD_WHISPLAY_BACKLIGHT_GPIO`
- `YOYOPOD_WHISPLAY_BACKLIGHT_ACTIVE_LOW`
- `YOYOPOD_WHISPLAY_BUTTON_GPIO`
- `YOYOPOD_WHISPLAY_BUTTON_ACTIVE_LOW`

The Whisplay defaults match the vendor board mapping:

- SPI bus `0`, chip select `0`, speed `100000000`
- DC GPIO `27`
- reset GPIO `4`
- backlight GPIO `22`, active low
- button GPIO `17`, active high

## Run On Pi

First extract the CI device bundle into the dev checkout and make the UI host executable:

```bash
mkdir -p device/ui/build
chmod +x device/ui/build/yoyopod-ui-host
```

```bash
yoyopod pi rust-ui-host --worker device/ui/build/yoyopod-ui-host --frames 10
```

Expected result:

- the Whisplay display shows changing test frames or the Rust-owned hub route
- the command prints a `ui.ready` payload
- the command prints a `ui.health` payload

For one-button validation, run both checks:

- no-touch `ui.tick` loop: should produce `button_events=0`
- physical button click while ticking: should emit `ui.input` and move focus

## Runtime Protocol

The Rust host accepts these UI-owner commands over line-delimited JSON:

- `ui.runtime_snapshot` - The runtime sends the latest app/runtime snapshot.
  Rust sends generic runtime state only through this payload. Rust applies
  call/loading/error preemption, owns the active screen, renders the screen,
  and emits `ui.screen_changed` when the Rust route changes.
- `ui.input_action` - Runtime or tests inject one semantic action
  (`advance`, `select`, `back`, `ptt_press`, `ptt_release`). Rust applies it to
  the active screen and emits `ui.intent` when Python runtime work is needed.
- `ui.tick` - Rust polls the Whisplay button, runs the one-button gesture
  machine, applies generated actions, emits intents, and renders dirty screens.

The Rust host receives generic `ui.runtime_snapshot` payloads only. It no
longer accepts `ui.show_hub`.

Legacy compatibility code still exists under `yoyopod/ui/rust_sidecar/`, while
the active CLI/test integration imports `yoyopod/ui/rust_host/`.
