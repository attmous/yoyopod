---
title: Remote Playback
description: The backend-issued playback and media import contract.
---

:::note[Canonical source]
This page is a summary. The authoritative document is
[`docs/features/REMOTE_PLAYBACK.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/REMOTE_PLAYBACK.md)
in the repository.
:::

The contract by which the backend can start playback on a device and import
media into its local library: message shapes, the media worker's
responsibilities, and how remote commands reconcile with what the child is
doing on the device.
