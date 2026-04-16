# mpv Local Playback Reference

**Last Updated:** 2026-04-07
**Hardware:** Raspberry Pi Zero 2W
**Audio Output:** Whisplay HAT (`wm8960`, `hw:1`)

## Overview

YoyoPod uses an app-managed mpv process as a local-only music backend.

This means:

- local playlists
- local files
- playback state and queue control through mpv JSON IPC

It does not mean Spotify or Amazon Music support in the current product.

## Runtime Role In YoyoPod

mpv currently provides:

- audio playback
- playback state and progress
- push events for track and property changes

YoyoPod adds on top of that:

- filesystem library scanning through `LocalMusicService`
- `.m3u` playlist discovery
- local-first `Listen` UX
- recent-track history
- one-button navigation
- metadata fallback via `tinytag`

## Recommended Dependencies

### Python Packages

| Package | Purpose |
|---|---|
| `tinytag` | Local file-tag fallback when mpv metadata is sparse |

### System Packages

| Package | Purpose |
|---|---|
| `mpv` | Core local playback engine and JSON IPC server |
| `alsa-utils` | Device inspection and audio smoke testing |

## Example `config/audio/music.yaml`

```yaml
audio:
  music_dir: /home/tifo/Music
  recent_tracks_file: data/media/recent_tracks.json
  mpv_socket: /tmp/yoyopod-mpv.sock
  mpv_binary: mpv
  default_volume: 100
```

## Example `config/device/hardware.yaml`

```yaml
media_audio:
  alsa_device: default
```

Notes:

- `hw:1` is the Whisplay HAT audio device in the current Raspberry Pi setup.
- `audio.music_dir` is the source of truth for local library scanning.
- `media_audio.alsa_device` is the source of truth for the mpv ALSA route.
- `.m3u` playlists can live anywhere under that music directory.
- mpv is spawned and supervised by the app; there is no separate music daemon to manage.

## Validation

```bash
pgrep -af mpv
yoyoctl pi validate music
yoyoctl remote smoke --with-music
yoyoctl remote logs --filter music --lines 100
```

Expected checks:

- mpv starts cleanly under app control
- local playlists are visible
- local tracks play through the configured ALSA device
- YoyoPod can reach mpv over the configured IPC socket

## Current Product Guidance

- Keep mpv as the local playback engine
- keep the YoyoPod product local-first
- do not treat streaming providers as active product sources unless that becomes a separate approved project decision

## References

- mpv manual: https://mpv.io/manual/stable/
- TinyTag: https://github.com/tinytag/tinytag
