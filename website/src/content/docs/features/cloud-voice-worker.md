---
title: Cloud Voice Worker
description: Cloud STT/TTS worker setup, secrets, and smoke validation.
---

:::note[Canonical source]
This page is a summary. The authoritative document is
[`docs/features/CLOUD_VOICE_WORKER.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/CLOUD_VOICE_WORKER.md)
in the repository.
:::

The Ask flow's speech-to-text and text-to-speech run through a cloud voice
worker, paired on-device with the `device/speech` host. The document covers
worker setup, secret management, and the smoke validation used to confirm a
working voice path end to end.
