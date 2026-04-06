# Mopidy Local Playback Reference

**Last Updated:** 2026-04-06  
**Hardware:** Raspberry Pi Zero 2W  
**Audio Output:** Whisplay HAT (`wm8960`, `hw:1`)

## Overview

YoyoPod currently uses Mopidy as a **local-only** music backend.

This means:

- local playlists
- local files
- playback state and queue control through Mopidy JSON-RPC

It does **not** mean Spotify or Amazon Music support in the current product.

## Runtime Role In YoyoPod

Mopidy currently provides:

- local playlist listing
- local file-library browse for shuffle
- playback state and progress
- tracklist control for `Now Playing`

YoyoPod adds on top of that:

- local-first `Listen` UX
- recent-track history
- one-button navigation

## Recommended Dependencies

### Python Packages

| Package | Purpose |
|---|---|
| `mopidy` | Core music server and JSON-RPC API |
| `mopidy-mpd` | Optional MPD compatibility for manual debugging with `mpc` |

### System Packages

| Package | Purpose |
|---|---|
| `gstreamer1.0-*` | Audio decode/playback runtime used by Mopidy |
| `alsa-utils` | Device inspection and audio smoke testing |

## Example `mopidy.conf`

```ini
[audio]
output = alsasink device=hw:1

[local]
enabled = true
media_dir = /home/tifo/Music

[m3u]
enabled = true
playlists_dir = /home/tifo/Music/playlists

[mpd]
enabled = true
hostname = 0.0.0.0
port = 6600
```

Notes:

- `hw:1` is the Whisplay HAT audio device in the current Raspberry Pi setup.
- YoyoPod relies on Mopidy's own media-dir and playlists-dir configuration.
- `yoyopod_config.yaml` should not duplicate Mopidy library paths.

## Validation

```bash
systemctl --user status mopidy
mpc update
mpc lsplaylists
mpc play
journalctl --user -u mopidy -f
```

Expected checks:

- Mopidy starts cleanly
- local playlists are visible
- local tracks play through `hw:1`
- YoyoPod can reach Mopidy over JSON-RPC

## Current Product Guidance

- Keep Mopidy as the local playback engine
- keep the YoyoPod product local-first
- do not treat streaming providers as active product sources unless that becomes a separate approved project decision

## References

- Mopidy docs: https://docs.mopidy.com/
- Mopidy Local extension: https://mopidy.com/ext/local/
- Mopidy M3U extension: https://mopidy.com/ext/m3u/
