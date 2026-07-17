---
title: Local-First Music
description: The direction for on-device music storage and playback.
---

:::note[Canonical source]
This page is a summary. The authoritative document is
[`docs/features/LOCAL_FIRST_MUSIC_PLAN.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/LOCAL_FIRST_MUSIC_PLAN.md)
in the repository.
:::

Music on yoyopod is local-first: tracks live on the device and play through
the app-managed `mpv` pipeline, with the cloud used for import rather than
streaming. This plan document lays out the direction, the library layout,
and how it interacts with remote playback commands from the backend.
