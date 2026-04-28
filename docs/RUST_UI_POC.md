# Rust UI PoC

The Rust UI PoC is an opt-in Whisplay-only hardware I/O test. It does not
replace the production Python LVGL UI.

## Build

```bash
yoyopod build rust-ui-poc
```

For host-only protocol tests:

```bash
yoyopod build rust-ui-poc --no-hardware-feature
```

CI builds the Whisplay worker on a native Linux ARM64 runner and uploads it as
the `yoyopod-rust-ui-poc-${{ github.sha }}` artifact.

For Raspberry Pi Zero 2W hardware validation, the deploy path is always:

1. Commit and push the branch.
2. Wait for the GitHub Actions `ui-rust` job to pass for the exact commit.
3. Download the matching `yoyopod-rust-ui-poc-<sha>` artifact.
4. Copy it to `workers/ui/rust/build/yoyopod-rust-ui-poc` on the Pi checkout.

Do not run `cargo build` or `yoyopod build rust-ui-poc` on the Pi Zero 2W unless
the user explicitly overrides this rule. Local builds are for developer
workstations or faster ARM64 boards only.

## Required Whisplay Environment

The first hardware backend reads explicit GPIO/SPI settings:

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

First copy the CI artifact into the dev checkout and make it executable:

```bash
mkdir -p workers/ui/rust/build
chmod +x workers/ui/rust/build/yoyopod-rust-ui-poc
```

```bash
yoyopod pi rust-ui-poc --worker workers/ui/rust/build/yoyopod-rust-ui-poc --frames 10
```

Expected result:

- the Whisplay display shows changing test frames
- the command prints a `ui.ready` payload
- the command prints a `ui.health` payload
