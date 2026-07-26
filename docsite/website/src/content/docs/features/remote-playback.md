---
title: Remote Playback
description: The live MQTT command/ack/event contract — backend-driven playback, the asset cache, and device-local media import.
---

The fully-specified, validated-on-hardware contract by which the backend
plays music on a device and imports media into its local library.

## The contract

Three topics ([Cloud Provisioning](/features/cloud-provisioning/)), with
a strict separation rule: **`ack` carries command acceptance only, `evt`
carries lifecycle only** — an ack/nack is never replayed as a lifecycle
event.

| Element | Values |
| --- | --- |
| Accepted commands | `play_track` · `pause` · `resume` · `stop` · `store_media` |
| ACK payload | `{command_id, status: "ack", payload: {command}}` |
| NACK payload | `{command_id, status: "nack", reason: "invalid_command"}` |
| Playback lifecycle (`type: "playback"`) | `buffering` · `playing` · `paused` · `stopped` · `completed` · `failed` |
| Import lifecycle (`type: "media_library"`) | `imported` · `failed` |

## The asset cache

Remote tracks are fetched into a bounded local cache **before** mpv ever
sees them — playback always runs from a local file, never the signed
backend URL, so short token lifetimes can't interrupt a song:

- cache key includes the sanitized `track_id`; checksums verified when
  provided,
- downloads run off the coordinator thread before the mpv load,
- LRU pruning by file mtime — and a just-fetched asset is protected from
  immediately evicting itself even when over cap.

Config: `remote_cache_dir` + `remote_cache_max_bytes`
(512 MiB default, 32 MiB floor — see
[the record library](/runtime/workers/media/)).

## Device-local media import (`store_media`)

The backend finalizes an uploaded household track → sends `store_media`
over the same dispatcher → the device downloads through the same cache
path → persists it under `music_dir/dashboard_uploads/` and updates
`Dashboard Uploads.m3u` → emits `media_library.imported` (or `failed`).
The backend stays the policy authority; the result surfaces as ordinary
local files in Listen — the import path that keeps
[local-first](/features/local-first-music/) honest.

## Session behavior worth knowing

One active remote session; a new valid `play_track` interrupts the
current one. Pending downloads are correlated by `commandId` +
activation generation, so a stale stop can't clear the *next* session. A
`stop` during buffering discards the pending asset — playback never
starts after a stop was acked. Duplicate `commandId`s are acked as
duplicates and not replayed (including `store_media`).

## Validated on hardware

The full sequence — ack → buffering → playing → paused → resume → stop,
plus `store_media` → `imported` and cached-asset replays — was observed
end-to-end on a real device. (One operational note from that run: the
device image logged VoIP recovery warnings from an unavailable
Liblinphone backend; it does not affect playback or import.)

:::note[Canonical source]
Condensed from
[`docs/features/REMOTE_PLAYBACK.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/REMOTE_PLAYBACK.md)
— whose header still says "yoyo-py"; the behavior described is the
current Rust runtime's.
:::
