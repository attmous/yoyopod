# Deployed Pi Dependency Snapshot

**Last Verified:** 2026-04-18  
**Target Device:** `rpi-zero`  
**SSH User:** `tifo`

This document is a live deployment snapshot of the Raspberry Pi environment currently running YoYoPod. It complements the architecture docs by showing the actual services, processes, packages, and native libraries the production device depends on today.

## Active Services

These services were running when this snapshot was taken:

- `yoyopod@raouf.service`
- `pisugar-server.service`

What that means in practice:

- YoYoPod itself is a systemd-managed application service
- PiSugar power telemetry, RTC, and watchdog transport come from the standalone `pisugar-server` system service

## Active Runtime Processes

The live process tree for YoYoPod was:

```text
uv run python yoyopod.py
  -> python3 yoyopod.py
     -> mpv --idle --no-video --input-ipc-server=/tmp/yoyopod-mpv.sock --audio-device=alsa/default
```

No separate Mopidy process or music daemon is part of the stack anymore.

## Core Functional Dependencies

### Application runtime

- `python3`
- `uv`
- YoYoPod virtual environment under `/home/raouf/yoyo-py/.venv`

### Music playback

- `mpv`
- `ffmpeg`
- ALSA runtime:
  - `libasound2`
  - `libasound2-data`
  - `libasound2-plugins`
- `alsa-utils`

### VoIP and voice notes

- `liblinphone12`
- `liblinphone++12`
- `libmediastreamer2-14`
- `libbctoolbox2`

### Power management

- `pisugar-server`
- `i2c-tools`

### Display / native UI

- vendored `liblvgl.so.9`
- `libyoyopod_lvgl_shim.so`

### Native VoIP bridge

- `libyoyopod_liblinphone_shim.so`

## Python-Level Dependencies Used By The App

These are the declared application-level Python dependencies relevant to the current product:

- `cffi`
- `requests`
- `loguru`
- `pyyaml`
- `tinytag`

Present in the project but not central to the current Whisplay Pi runtime:

- `flask`
- `flask-socketio`
- `flask-cors`
- `python-socketio`
- `pynput`
- `pygame` appears to be legacy and is not the production music path

## Hardware-Coupled Dependencies

### Audio hardware

Live ALSA playback devices on the Pi:

- `card 0`: `wm8960-soundcard`
- `card 1`: `vc4-hdmi`

Current YoYoPod playback is using:

```text
mpv -> ALSA default -> wm8960-soundcard -> bcm2835 I2S -> WM8960 codec
```

### Display hardware

Production rendering path on this device is:

```text
YoyoPodApp -> LVGL backend -> Whisplay adapter -> SPI display
```

### Power hardware

Current power path is:

```text
YoyoPodApp -> PowerManager -> PiSugar backend -> /tmp/pisugar-server.sock or local PiSugar TCP/socket transport
```

## Native Library Dependencies Seen On The Device

### LVGL shim

The LVGL shim currently links against:

- `liblvgl.so.9`
- `libc`

### Liblinphone shim

The Liblinphone shim currently links against:

- `liblinphone.so.12`
- `libmediastreamer2.so.14`
- `libbelle-sip.so.3`
- `libbctoolbox.so.2`
- `libasound.so.2`
- `libpulse.so.0`
- codec / media support libraries pulled through Liblinphone and FFmpeg

Important note:

- there is **no PulseAudio daemon dependency in the current YoYoPod service flow**
- but `libpulse.so.0` still appears as a transitive shared-library dependency of Liblinphone on this Pi

## What Is No Longer Part Of The Stack

Removed from the live Pi:

- Mopidy
- GStreamer
- `mopidy.service`
- provider-driven music playback infrastructure

Current product direction is local-first music via `mpv`, not a general music-server stack.

## Operational Observations

At the time of capture:

- `yoyopod@raouf.service` was healthy
- `pisugar-server.service` was healthy
- memory usage was approximately `231 MB / 416 MB`
- YoYoPod had one long-lived `python3` process and one long-lived `mpv` child


## Cloud Integration Dependencies

### Cloudflare Tunnel

The backend is exposed through a Cloudflare tunnel (token-based, managed via  systemd service). The MQTT broker WebSocket endpoint is routed through Cloudflare:

- Cloudflare route:  → 
- Mosquitto listens on port 8083 with WebSocket protocol enabled

### Mosquitto MQTT Broker

Mosquitto runs as a snap service on the host machine with two listeners:

- Port 1883: plain TCP (LAN access)
- Port 8083: WebSocket (routed via Cloudflare tunnel for Pi access over the internet)

Config at: 

### Pi MQTT Transport

The Pi connects to the MQTT broker using WebSocket transport over WSS:443 via Cloudflare. Config in :

- 
- 
- 
- 

Env override: 

## Source Of Truth For This Snapshot

This snapshot was built from:

- live SSH inspection of `rpi-zero`
- `systemctl status`
- `ps` / `pstree`
- `aplay -l`
- `amixer`
- `dpkg -l`
- `ldd` on the two native shims
- repo config in:
  - `config/app/core.yaml`
  - `config/audio/music.yaml`
  - `config/device/hardware.yaml`
  - `config/voice/assistant.yaml`
  - `config/communication/calling.yaml`
  - `config/communication/messaging.yaml`
  - `deploy/pi-deploy.yaml`
