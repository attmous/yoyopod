---
title: Local-First Music
description: The decision — Listen is local-first and local-only, via an app-owned mpv backend and a filesystem library.
---

This page records a product decision, and the shape that follows from it.

## The decision

**Listen is local-first and local-only.** Spotify, Amazon Music, and
other streaming providers are not active Listen sources. Music on
yoyopod means on-device files, played by an app-owned mpv backend over a
filesystem library. Streaming providers must not be treated as active
sources unless a separate, explicit decision reverses this.

## The product shape

The Listen root opens a small local library menu — **Playlists**,
**Recent**, **Shuffle**. `Artists` and `Albums` views are deferred until
the local-first baseline is stable. (The UI treatment — the wheel and
the arc hero — is specified in the
[UI guide's design gallery](/ui/mockups/).)

## The backend contract

- **Playlists** are `.m3u` files discovered anywhere under
  `audio.music_dir` (`config/audio/music.yaml`).
- **Recents** are recorded by yoyopod itself from mpv track-change
  events — capped, local-only.
- **Shuffle** builds its queue from filesystem track paths.
- Metadata falls back to local tag reads when mpv's metadata is sparse.

The cloud enters only as an *import* path, never a streaming path: the
backend can push tracks into the local library via `store_media`
([Remote Playback](/features/remote-playback/)), after which they're
ordinary local files.

The full mechanics: [the record library](/runtime/workers/media/)
(process + cache), [Audio Stack](/hardware/audio-stack/) (signal path),
[MPV Dependencies](/features/mpv-dependencies/) (install contract).

:::note[Canonical source]
Condensed from
[`docs/features/LOCAL_FIRST_MUSIC_PLAN.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/LOCAL_FIRST_MUSIC_PLAN.md)
(decision dated 2026-04-07).
:::
