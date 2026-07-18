---
title: Audio Path
description: Speaker, microphone, and the signal chain between them.
---

*Every centimeter of the audio path, from file to speaker and voice to network.*

:::caution[Vision stub]
Placeholder in the vision docs — the structure is decided, the content is
not written yet. As-built engineering docs live in the main docs site
(`website/` in the repository).
:::

## Overview

- Audio is the product: music, stories, calls, and voice messages all travel this path
- The two directions: playback (file to speaker) and capture (voice to network)
- Why local-first matters here: music and stories must play with no internet
- The calm constraint: one speaker, one microphone, no headphone-jack decision made yet (TBD)

## Key components

- Speaker and its amplifier stage (prototype: on the Whisplay HAT; product part TBD)
- Microphone and its capture path (prototype placement and part TBD in docs)
- Codec / DAC-ADC chain between the compute board and the transducers (TBD for product board)
- Volume control: where limits live in hardware vs. software, including a maximum-loudness ceiling for kids' hearing (TBD)

## Interfaces & contracts

- Playback: the media worker drives mpv, which owns the file-to-output leg of the chain
- Capture: hold-to-talk routes microphone audio into the voip worker and the speech worker
- The kernel audio interface the workers sit on (ALSA details covered in the as-built engineering docs, `website/` in the repository)
- Mixing and arbitration: what happens when a call arrives during music playback — who owns the speaker (TBD)

## Today vs. target

- Today: Whisplay HAT audio hardware on the Pi Zero 2W prototype
- Target: product-board audio design with its own speaker, mic, and codec choices (TBD)
- Fixed by intent: speaker + microphone, voice-message and call quality good enough for a grandparent's ear
- Open: acoustic tuning, mic noise handling for outdoor use, and any hardware volume limiting (TBD)

## Open questions

- TODO: What loudness ceiling do we commit to for kids' hearing, and is it enforced in hardware or software?
- TODO: Does the product device offer any wired or wireless headphone path, or speaker-only?
- TODO: What echo/noise handling does push-to-talk need for a child talking outdoors near traffic?
- TODO: Who arbitrates the speaker when a call and music playback collide, and is that a hardware or runtime contract?
