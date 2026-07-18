---
title: Audio Path
description: Speaker, microphone, and the signal chain between them.
---

*Every centimeter of the audio path, from file to speaker and voice to network.*

## Overview

Two independent audio paths share one piece of hardware. Music and calls
travel separate software stacks that converge on a single **WM8960 codec**
on the Whisplay HAT — knowing which path a sound takes is the first step of
every audio debug, because music dead but calls fine (or vice versa)
localizes the fault immediately; the paths only share the codec. Playback
is local-first: mpv is the local-only playback engine, and streaming
providers are not treated as active sources.

## Key components

**The music path:** the media worker spawns and supervises **mpv** — no
separate music daemon, no Mopidy, no GStreamer; mpv dies with its host. The
worker does the library work (filesystem scanning, playlist discovery,
recents, shuffle queues) and hands mpv file paths; it never decodes audio
itself. mpv pushes property events over its IPC socket, which is how Now
Playing stays current without polling.

**The call path:** the voip worker runs **Liblinphone**, which routes to
the same ALSA codec directly.

**The hardware:** card 0 is the `wm8960-soundcard` (bcm2835 I²S), and
everything routes there — out to speaker or headphone. HDMI audio exists on
card 1 and is unused.

## Interfaces & contracts

- **Volume** is one app-facing value written to two places: the system
  mixer (via `amixer`) *and* mpv — the levels multiply, which is the first
  thing to check when audio is quiet. On the production image the active
  ALSA controls are `Speaker`, `Headphone`, and `Playback`.
- **Config** lives in two files: the music config (library directory, mpv
  socket and binary, default volume) and the device hardware config (the
  ALSA device routes for media, communication, and voice audio).
- **Install contract:** the Pi image needs `mpv` and `alsa-utils`;
  validation is deploy, watch the logs, and confirm mpv starts under app
  control and answers on its IPC socket.

:::note[One discrepancy in the canonical docs]
The canonical mpv doc's header names the audio device as `hw:1`, while the
config and the device-verified audio stack route through `default` →
card 0 `wm8960-soundcard`. Trust the verified card-0 route; the `hw:1` note
appears to predate the current image.
:::

## Today vs. target

Today: the Whisplay HAT's speaker, microphone, and WM8960 codec on the Pi
Zero 2W prototype, verified against the live device. Target: a product
board with its own speaker, microphone, and codec choices — still to be
decided. Fixed by intent: speaker plus microphone, and playback that keeps
working with no internet. Open: acoustic tuning, hardware volume limiting,
and the headphone question.

## Open questions

- TODO: What loudness ceiling do we commit to for kids' hearing, and is it enforced in hardware or software?
- TODO: Does the product device offer any wired or wireless headphone path, or speaker-only?
- TODO: What echo/noise handling does push-to-talk need for a child talking outdoors near traffic?
- TODO: Who arbitrates the speaker when a call and music playback collide, and is that a hardware or runtime contract?

:::note[Sources]
Condensed from
[`docs/hardware/AUDIO_STACK.md`](https://github.com/attmous/yoyopod/blob/main/docs/hardware/AUDIO_STACK.md)
and
[`docs/features/MPV_DEPENDENCIES.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/MPV_DEPENDENCIES.md),
and the as-built docs site (`website/` in the repository): the Audio Stack
and MPV Dependencies pages.
:::
