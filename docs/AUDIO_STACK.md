# YoyoPod Audio Stack

**Last Verified:** 2026-04-08  
**Verified Against:** `origin/main` plus live `rpi-zero` runtime

## Overview

YoyoPod now uses an app-managed `mpv` process for music playback and Liblinphone for call audio.

For music playback, the runtime path is:

```text
yoyopod.py
  -> yoyopy.main
     -> YoyoPodApp
        -> LocalMusicService
        -> MpvBackend
           -> MpvProcess
              -> mpv --idle --no-video --input-ipc-server=/tmp/yoyopod-mpv.sock --audio-device=alsa/default
           -> MpvIpcClient
              -> JSON IPC over /tmp/yoyopod-mpv.sock
        -> ALSA default PCM
        -> card 0: wm8960-soundcard
        -> bcm2835 I2S -> WM8960 codec
        -> speaker / headphone output
```

For calls and voice notes, the audio runtime is separate:

```text
YoyoPodApp
  -> VoIPManager
     -> LiblinphoneBackend
        -> ALSA: wm8960-soundcard
        -> same WM8960 codec / physical output path
```

So music and VoIP use different software stacks, but they converge on the same Raspberry Pi audio hardware.

## Application Layer

`YoyoPodApp` owns the audio stack startup in production.

- `audio.music_dir` selects the local music root.
- `audio.mpv_socket` selects the mpv IPC socket.
- `audio.mpv_binary` selects the binary to spawn.
- `audio.alsa_device` selects the mpv ALSA target.
- `audio.default_volume` is applied at startup through the shared output-volume controller.

Current production config shape:

```yaml
audio:
  music_dir: /home/tifo/Music
  mpv_socket: /tmp/yoyopod-mpv.sock
  mpv_binary: mpv
  alsa_device: default
  default_volume: 100
```

## Music Control Path

### 1. Local library selection

`LocalMusicService` is the app-facing music layer.

It owns:

- scanning `audio.music_dir`
- finding `.m3u` playlists
- loading recent tracks
- building `Shuffle` queues from local files

It does **not** decode or play audio itself. It hands filesystem paths to the backend.

### 2. Playback backend

`MpvBackend` is the production music backend.

It owns:

- starting and stopping the `mpv` process
- loading tracks or playlist files
- play/pause/stop/next/previous commands
- reading current track metadata
- receiving push events from mpv

The backend is app-managed. There is no separate music daemon anymore.

### 3. mpv process

`MpvProcess` spawns mpv in idle mode with no video and a JSON IPC socket.

Current launch shape:

```text
mpv --idle --no-video --input-ipc-server=/tmp/yoyopod-mpv.sock --audio-device=alsa/default
```

This was verified live on `rpi-zero` on 2026-04-08.

### 4. mpv IPC

`MpvIpcClient` talks to mpv over `/tmp/yoyopod-mpv.sock`.

It is used for:

- playback commands
- volume commands
- property reads
- push event subscription for:
  - `path`
  - `metadata`
  - `duration`
  - `media-title`
  - `pause`
  - `idle-active`

That is how `Now Playing` and runtime playback state stay current without polling an external daemon.

## Volume Path

`OutputVolumeController` owns one app-facing output volume across ALSA and mpv.

It does two things:

1. writes the system mixer through `amixer`
2. pushes the same volume into the connected `mpv` backend

In priority order it tries ALSA controls like:

- `Master`
- `Speaker`
- `Headphone`

On the current Pi, the active relevant mixer controls are:

- `Speaker`
- `Headphone`
- `Playback`

Verified live on `rpi-zero`:

- `Speaker`: `100%` / `+6.00dB`
- `Headphone`: `100%` / `+6.00dB`

So the effective music loudness comes from:

```text
YoyoPod shared volume
  -> ALSA mixer controls
  -> mpv volume property
  -> WM8960 analog output stage
```

## Hardware Path On The Pi

Verified live with `aplay -l` on 2026-04-08:

- `card 0`: `wm8960-soundcard`
- `device 0`: `bcm2835-i2s-wm8960-hifi`

That means the practical hardware output path is:

```text
mpv
  -> ALSA `default`
  -> ALSA card 0 (`wm8960-soundcard`)
  -> bcm2835 I2S digital audio
  -> WM8960 codec
  -> speaker / headphone analog output
```

There is also HDMI audio on card 1, but the current YoyoPod music runtime is using the WM8960 path, not HDMI.

## Call Audio Relationship

VoIP is not routed through mpv.

Liblinphone uses its own ALSA device selection from `config/voip_config.yaml`, typically:

- playback: `ALSA: wm8960-soundcard`
- ringer: `ALSA: wm8960-soundcard`
- capture: `ALSA: wm8960-soundcard`
- media: `ALSA: wm8960-soundcard`

So:

- music path: `mpv -> alsa/default -> wm8960`
- VoIP path: `Liblinphone -> ALSA: wm8960-soundcard`

They are separate software paths that meet at the same codec/hardware.

## Operational Notes

- There is no Mopidy or GStreamer dependency in the current production music path.
- `mpv` is spawned by the app and dies with the app.
- If music works but is quiet, check both:
  - YoyoPod shared volume
  - ALSA `Speaker` / `Headphone` mixer levels
- If `Now Playing` is wrong, the most relevant layers are:
  - `LocalMusicService`
  - `MpvBackend`
  - `MpvIpcClient`
  - file tag fallback in `Track.from_mpv_metadata()`

## Source Files

- `yoyopy/app.py`
- `yoyopy/audio/local_service.py`
- `yoyopy/audio/music/backend.py`
- `yoyopy/audio/music/process.py`
- `yoyopy/audio/music/ipc.py`
- `yoyopy/audio/music/models.py`
- `yoyopy/audio/volume.py`
- `config/yoyopod_config.yaml`
- `config/voip_config.yaml`
