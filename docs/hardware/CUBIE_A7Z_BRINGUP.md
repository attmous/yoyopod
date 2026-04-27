# Radxa Cubie A7Z Bringup

This note records the current YoYoPod bringup path for the Radxa Cubie A7Z and the main findings from hardware validation.

It is intentionally practical:

- what was required to make the board usable as a YoYoPod target
- what was verified on-device
- what is still risky, unsupported, or unresolved

## Scope

This bringup was done on:

- board: `Radxa Cubie A7Z`
- OS: `Debian Bullseye`
- kernel family: Radxa vendor BSP `5.15.147-18-a733`
- user: `radxa`
- project dir: `~/yoyopod-core`

The Cubie A7Z is now a usable YoYoPod development target, but it is not yet a drop-in replacement for the Raspberry Pi Zero 2W. The major caveat is the Whisplay physical button behavior on this board.

## Bringup Summary

### 1. Base system packages

Install the general build and runtime dependencies:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y \
  build-essential git curl wget cmake pkg-config \
  i2c-tools spi-tools \
  libffi-dev libssl-dev python3-dev \
  libasound2-dev libopus-dev libspeexdsp-dev \
  libdrm-dev libinput-dev libevdev-dev libxkbcommon-dev
```

Additional runtime packages used later during validation:

```bash
sudo apt install -y mpv espeak-ng unzip
```

## 2. Python and project environment

Install `uv` and Python `3.12`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
uv python install 3.12
```

Important note:

- Debian system `python3` remains `3.9.2`
- YoYoPod should use `uv` / `.venv`, not replace `/usr/bin/python3`

Project setup on the board:

```bash
cd ~/yoyopod-core
~/.local/bin/uv venv --python 3.12 .venv
~/.local/bin/uv sync --extra dev
```

## 3. Hostname and timezone

```bash
sudo timedatectl set-timezone Europe/Berlin
sudo hostnamectl set-hostname cubie-a7z
```

## 4. SPI for Whisplay display

Enable the Cubie SPI1 spidev overlay.

On this image, the Radxa tooling expected overlays to be managed through `rsetup`.

Verified result:

- `/dev/spidev1.0` present

## 5. TWI7 / I2C for PiSugar 3 and WM8960

For Whisplay audio and PiSugar 3 on Cubie A7Z:

- enable `twi7`
- adjust the TWI7 clock to `100 kHz` per PiSugar guidance

Verified result:

- `/dev/i2c-7` present
- active TWI7 clock set to `100000`

Other board I2C buses visible during bringup:

- `/dev/i2c-13`
- `/dev/i2c-14`
- `/dev/i2c-20`

## 6. Whisplay driver and WM8960 audio

Use the Cubie A7Z-specific Whisplay install flow from the PiSugar repo.

Expected outcome:

- SPI display path working
- WM8960 codec on I2C bus `7`
- `wm8960-soundcard` available for playback and capture

Observed validation:

- Whisplay display worked
- WM8960 audio worked
- `aplay -L` and `arecord -L` exposed `wm8960-soundcard`

## 7. PiSugar 3

Install and configure `pisugar-server` on bus `7`.

Expected configuration:

- socket path: `/tmp/pisugar-server.sock`
- I2C bus: `7`

Verified behavior when PiSugar was attached and powered correctly:

- battery telemetry available
- charging state visible
- external power visible
- RTC accessible and syncable

RTC status was checked and synchronized to the NTP-synced system clock.

## 8. Board-specific YoYoPod config

Cubie A7Z support is configured through a tracked board override:

- `config/boards/radxa-cubie-a7z/audio/music.yaml`
- `config/boards/radxa-cubie-a7z/device/hardware.yaml`

Current Cubie override:

- `audio.music_dir: /home/radxa/Music`
- `power.watchdog_i2c_bus: 7`

Board selection uses:

- `YOYOPOD_CONFIG_BOARD=radxa-cubie-a7z`

Known boards can also auto-detect through `ConfigManager`.

## 9. Voice / media runtime

The Cubie board was validated with:

- `mpv`
- `liblinphone-dev`
- `linphone-common`
- `espeak-ng`
- Vosk Python package from the project environment
- local Vosk model installed at:
- `~/yoyopod-core/models/vosk-model-small-en-us`

Verified state on the board:

- `capture_available = True`
- `stt_available = True`
- `tts_available = True`

## 10. Test music content

For local-first music validation, sample tracks were placed under:

- `/home/radxa/Music/Test Samples`

And a simple playlist was created:

- `/home/radxa/Music/YoYoPod Test Playlist.m3u`

## Current Verified State

The Cubie A7Z is currently able to run YoYoPod with:

- Python `3.12` in the project `.venv`
- working SPI display path
- working Whisplay display
- working WM8960 playback/capture path
- working local music playback path
- working Liblinphone backend on Bullseye
- working local voice-command asset install

## Findings And Known Issues

### 1. Whisplay physical button is not safe on Cubie A7Z

This is the most important finding.

The Whisplay repository explicitly warns for Radxa Cubie A7Z:

- the physical button on Whisplay HAT is not safe to use on this board
- pressing it may shut the board down or make it lose power immediately

That matched live behavior during testing.

What was observed:

- with Whisplay attached, display and audio worked
- with Whisplay and PiSugar stacked together, pressing the Whisplay button reliably took the Cubie down immediately
- the same shutdown happened even after stopping:
  - `yoyopod`
  - `pisugar-server`

So this is not a YoYoPod application bug and not a PiSugar watchdog/software action issue.

### 2. PiSugar software tap actions were not the cause

PiSugar button actions were checked live and were disabled:

- single tap disabled
- double tap disabled
- long tap disabled
- soft poweroff disabled

That rules out PiSugar button software behavior as the root cause of the immediate shutdown when pressing the Whisplay button.

### 3. The PiSugar board makes the Whisplay button failure more reproducible

One interesting observation:

- Whisplay alone could appear to work
- Whisplay + PiSugar made the shutdown behavior reproducible

Current interpretation:

- the Whisplay button path is fundamentally unsafe on Cubie A7Z
- PiSugar likely amplifies the failure through stack mechanics, shared power behavior, grounding, or electrical margin

This does not make the Whisplay button safe without PiSugar. It only means the failure threshold becomes easier to hit when PiSugar is attached.

### 4. Recommended temporary hardware setup

For now, the safest practical setup is:

- remove PiSugar 3 from the Cubie stack
- power the Cubie directly from USB
- do not use the Whisplay physical button

If one-button input is needed later, preferred next options are:

- use the PiSugar custom function button as a semantic input source
- or add an external button wired to a known-safe `3.3V` GPIO path

### 5. System Python should not be replaced

The Cubie image still uses Debian Bullseye system Python:

- `python3 = 3.9.2`

YoYoPod uses:

- `uv`
- Python `3.12`
- project `.venv`

Do not change `/usr/bin/python3` on this image.

### 6. ALSA card index ordering is not stable

ALSA card numbering can vary after reboot.

Recommendation:

- target playback/capture devices by device name
- avoid assuming a fixed card index for `wm8960-soundcard`

### 7. Avoid casual kernel upgrades

The current working state depends on the Radxa vendor BSP kernel and overlays.

At the time of bringup, this kernel line provided the needed behavior for:

- Wi-Fi
- SPI overlays
- TWI overlays
- Whisplay display
- WM8960 audio
- Radxa overlay tooling

Do not upgrade or replace the kernel casually unless there is a specific hardware issue that requires it.

## Open Points

### 1. Final one-button UX on Cubie A7Z

Because the Whisplay physical button is unsafe on this board, Cubie A7Z needs a different one-button input strategy.

Open options:

- PiSugar custom button as app input
- external safe GPIO button
- no one-button mode on Cubie for now

### 2. Exact electrical root cause of the Whisplay button failure

The behavior is confirmed, but the exact electrical mechanism is still not fully characterized.

Open questions:

- whether the failure is caused by the Whisplay `KEY` signal level on Cubie A7Z
- whether the stack introduces a power/ground/mechanical interaction when PiSugar is attached
- whether there is a safe hardware workaround

This was important enough to justify contacting PiSugar support for clarification.

### 3. Cubie-specific docs and validation flow

Most tracked project docs still assume Raspberry Pi Zero 2W as the main target.

The Cubie A7Z is now usable enough that follow-up docs may be worth adding later for:

- Cubie-specific deploy workflow
- Cubie-specific smoke checklist
- Cubie-safe one-button input recommendations

## Recommended Working Mode Right Now

For immediate development:

1. use Cubie A7Z powered directly by USB
2. keep PiSugar detached unless specifically testing PiSugar features
3. do not press the Whisplay physical button on Cubie A7Z
4. use SSH plus service restarts for app validation
5. use the Cubie board config override and the project `.venv`

This is the safest current path while keeping the board productive for display, audio, VoIP, music, and local voice-command development.
