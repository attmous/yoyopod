# Local-First Music Plan

**Last Updated:** 2026-04-07

## Decision

YoYoPod's `Listen` experience is now local-first and local-only.

The product no longer treats Spotify, Amazon Music, or other providers as active `Listen` sources. `Listen` now means on-device music managed through an app-owned mpv backend and filesystem library.

## Product Shape

The `Listen` root mode opens a small local library menu:

- `Playlists`
- `Recent`
- `Shuffle`

`Artists` and `Albums` are deferred until the local-first baseline is stable.

## Backend Contract

YoYoPod now uses an app-managed mpv backend plus filesystem scanning:

- local playlists are discovered from `.m3u` files under `audio.music_dir`
- recent tracks are stored by YoYoPod from mpv track-change events
- shuffle builds a queue from filesystem track paths
- metadata falls back to local tag reads when mpv metadata is sparse

The local library root lives in `config/audio/music.yaml` under `audio.music_dir`.
