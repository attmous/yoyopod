---
title: Audio Stack
description: How music (mpv) and calls (Liblinphone) travel separate software paths that converge on one WM8960 codec.
---

Two independent audio paths share one piece of hardware. Understanding
which path a sound takes is the first step of every audio debug.

## The two paths

**Music:**

```
yoyopod-runtime → media-host → mpv (--idle --no-video
  --input-ipc-server=/tmp/yoyopod-mpv.sock --audio-device=alsa/default)
  → ALSA "default" → card 0 wm8960-soundcard → bcm2835 I2S → WM8960
  → speaker / headphone
```

**Calls:**

```
yoyopod-runtime → voip-host → Liblinphone → ALSA wm8960-soundcard
```

Separate stacks, same codec. There is **no music daemon** — mpv is
spawned and supervised by the media host and dies with it. (No Mopidy,
no GStreamer.)

The media host does the library work — filesystem scanning, `.m3u`
discovery, recents, shuffle queues — and hands mpv *paths*; it never
decodes audio itself. mpv pushes property events (`path`, `metadata`,
`duration`, `media-title`, `pause`, `idle-active`) over its IPC socket,
which is how Now Playing stays current without polling.

## The volume path

One app-facing volume, written to two places: the system mixer (via
`amixer`) **and** mpv. ALSA control priority: `Master` → `Speaker` →
`Headphone`; on the production image the active controls are `Speaker`,
`Headphone`, and `Playback` (verified at 100% / +6.00 dB).

## Hardware facts

From `aplay -l` on the device: **card 0** = `wm8960-soundcard`
(device 0: `bcm2835-i2s-wm8960-hifi`) — everything routes here. HDMI
audio exists on card 1 and is unused.

## Config

| File | Keys |
| --- | --- |
| `config/audio/music.yaml` | `audio.music_dir` (`/home/tifo/Music`), `recent_tracks_file`, `mpv_socket`, `mpv_binary`, `default_volume` |
| `config/device/hardware.yaml` | `media_audio.alsa_device` (`default`), plus `communication_audio.*` and `voice_audio.*` device ids |

## Troubleshooting

- **Quiet audio** → check *both* the yoyopod shared volume and the ALSA
  `Speaker`/`Headphone` levels — they multiply.
- **Wrong Now Playing** → inspect the media host's snapshot and the mpv
  IPC events; the UI only renders what the snapshot says.
- **Which path is broken?** Music dead but calls fine (or vice versa)
  localizes the fault immediately — the paths only share the codec.

See also: the [media worker profile](/runtime/workers/media/) for the
process mechanics, and [MPV Dependencies](/features/mpv-dependencies/)
for the install contract.

:::note[Canonical source]
Condensed from
[`docs/hardware/AUDIO_STACK.md`](https://github.com/attmous/yoyopod/blob/main/docs/hardware/AUDIO_STACK.md)
(last verified 2026-04-08 against the live device).
:::
