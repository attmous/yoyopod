---
title: Audio Stack
description: WM8960 codec, ALSA routing, and the mpv and Liblinphone audio paths.
---

:::note[Canonical source]
This page is a summary. The authoritative document is
[`docs/hardware/AUDIO_STACK.md`](https://github.com/attmous/yoyocore/blob/main/docs/hardware/AUDIO_STACK.md)
in the repository.
:::

Audio runs through the WM8960 codec on the Whisplay HAT over I2S. Music
playback is an app-managed `mpv` process writing to the ALSA `default`
device (card 0, `wm8960-soundcard`); calls go through Liblinphone to the
same codec. The microphone and speaker are part of the Whisplay bundle. The
audio-stack document maps the full routing, the relevant config keys under
`config/device/hardware.yaml` (communication, media, and voice audio), and
the debugging paths when sound goes missing.
