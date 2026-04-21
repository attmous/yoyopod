# YoyoPod Audio Stack

**Last Verified:** 2026-04-21  
**Verified Against:** live `piz` runtime on `feat/music-management-playback`

## Overview

YoYoPod uses an app-managed `mpv` process for music playback and targets the WM8960 codec directly over ALSA.

Current deployed music path:

```text
yoyopod.py
  -> YoyoPodApp
     -> LocalMusicService
     -> MpvBackend
        -> MpvProcess
           -> mpv --idle --no-video --input-ipc-server=/tmp/yoyopod-mpv.sock --audio-device=alsa/sysdefault:CARD=wm8960soundcard
        -> MpvIpcClient
           -> JSON IPC over /tmp/yoyopod-mpv.sock
     -> WM8960 ALSA playback device
     -> speaker / headphone output
```

On the deployed Pi, `pipewire`, `pipewire-pulse`, and `wireplumber` are masked so they do not fight YoYoPod for the WM8960 card or rewrite codec mixer state underneath the app.

## Config Ownership

- `config/audio/music.yaml` owns music policy such as `music_dir`, `mpv_socket`, and `default_volume`
- `config/device/hardware.yaml` owns `media_audio.alsa_device`
- `/etc/default/yoyopod` can override the final ALSA device through `YOYOPOD_ALSA_DEVICE`

Current deployed value:

```yaml
media_audio:
  alsa_device: "sysdefault:CARD=wm8960soundcard"
```

## Hardware Reality On `piz`

Verified with `aplay -L` and `/proc/asound/cards`:

- `card 0`: `vc4-hdmi`
- `card 1`: `wm8960-soundcard`

So the correct YoYoPod music path is not ALSA `default`. It is the WM8960 card explicitly:

```text
mpv
  -> ALSA sysdefault:CARD=wm8960soundcard
  -> bcm2835 I2S
  -> WM8960 codec
  -> analog speaker / headphone output
```

## Volume Strategy

`OutputVolumeController` owns the shared app-facing output volume.

For WM8960-class hardware the effective production rule is:

- keep codec output headroom high
- use mpv volume as the user-facing playback loudness

Current deployed headroom fix:

- `Playback` pinned to `100%`
- `Speaker` pinned to `100%`
- `Headphone` pinned to `100%`

Why:

- on WM8960, app-style percentages like `50%` on the hardware `Playback` control map to very low analog output levels
- using those hardware controls as the primary user volume made the device appear to be "playing with no sound"

Current loudness path:

```text
YoYoPod shared volume
  -> mpv volume property
  -> WM8960 codec already held at calibrated headroom
```

## Local And Remote Music

Local playlist playback and backend-issued remote playback both converge on the same `mpv` process.

Remote playback behavior:

- backend issues `play_track`
- device downloads the authorized asset into the bounded remote cache
- mpv plays from the cached local file

Device-local import behavior:

- backend issues `store_media`
- device downloads the finalized household track
- device persists it into `YOYOPOD_MUSIC_DIR/dashboard_uploads/`
- device updates `Dashboard Uploads.m3u`
- local `Listen` surfaces can then play it as a normal local playlist

## Operational Notes

- if music says `playing` but the device is silent, check the actual ALSA device first; `alsa/default` is not acceptable on this hardware
- if `Playback` drops back down unexpectedly after boot, verify `pipewire`, `pipewire-pulse`, and `wireplumber` are still inactive
- if mpv is alive but no track advances, inspect `/tmp/yoyopod-mpv.sock`
- if imported dashboard tracks do not appear locally, inspect `Dashboard Uploads.m3u` and the `dashboard_uploads/` directory under the configured music dir

## Source Files

- `src/yoyopod/audio/music/process.py`
- `src/yoyopod/audio/music/backend.py`
- `src/yoyopod/audio/volume.py`
- `src/yoyopod/cloud/manager.py`
- `config/device/hardware.yaml`
- `/etc/default/yoyopod`
