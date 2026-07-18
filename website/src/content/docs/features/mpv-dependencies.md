---
title: MPV Dependencies
description: The install, config, and validation contract for mpv as yoyopod's local-only playback engine.
---

mpv is the app-managed, local-only playback engine — spawned and
supervised by the media host, never a separate daemon. This page is the
install-and-verify contract for the Pi image.

## System packages

| Package | Purpose |
| --- | --- |
| `mpv` | the playback engine + its JSON IPC server |
| `alsa-utils` | device inspection and audio smoke testing |

## The config contract

```yaml
# config/audio/music.yaml
audio:
  music_dir: /home/tifo/Music          # source of truth for library scanning
  recent_tracks_file: data/media/recent_tracks.json
  mpv_socket: /tmp/yoyopod-mpv.sock
  mpv_binary: mpv
  default_volume: 100
```

```yaml
# config/device/hardware.yaml
media_audio:
  alsa_device: default                  # source of truth for mpv's ALSA route
```

`.m3u` playlists can live anywhere under `music_dir`. mpv's division of
labor with the media host: mpv does playback, state/progress, and push
events; the host does scanning, playlist discovery, recents, shuffle,
and the one-button UX ([the record library](/runtime/workers/media/)).

:::note[One discrepancy in the canonical doc]
Its header names the Whisplay audio device as `hw:1`, while the config
examples and the verified [Audio Stack](/hardware/audio-stack/) route
through `alsa_device: default` → **card 0** `wm8960-soundcard`. Trust
the Audio Stack page (verified with `aplay -l` on the device); the
`hw:1` note appears to predate the current image.
:::

## Validation on device

```bash
yoyopod target deploy --branch <branch>
yoyopod target logs --filter music --lines 100
ssh <user>@<host> 'pgrep -af mpv'
```

Expected: mpv starts cleanly under app control, playlists visible,
tracks audible through the configured ALSA device, and the host reaches
mpv over the IPC socket.

## Product guidance

Keep mpv as the local playback engine; keep the product
[local-first](/features/local-first-music/); do not treat streaming
providers as active sources without an explicit reversal of that
decision.

:::note[Canonical source]
Condensed from
[`docs/features/MPV_DEPENDENCIES.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/MPV_DEPENDENCIES.md)
(last updated 2026-04-07). mpv reference: the
[mpv manual](https://mpv.io/manual/stable/).
:::
