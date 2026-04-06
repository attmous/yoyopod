# Local-First Music Plan

**Last Updated:** 2026-04-06

## Decision

YoyoPod's `Listen` experience is now local-first and local-only.

The product no longer treats Spotify, Amazon Music, or other providers as active `Listen` sources. `Listen` now means on-device music managed through Mopidy's local and file backends.

## Product Shape

The `Listen` root mode opens a small local library menu:

- `Playlists`
- `Recent`
- `Shuffle`

`Artists` and `Albums` are deferred until the local-first baseline is stable.

## Backend Contract

YoyoPod keeps Mopidy as the playback engine, but wraps it through a local-only facade:

- local playlists are filtered to `m3u:` playlist URIs
- recent tracks are stored by YoyoPod from track-change events
- shuffle builds a queue from local/file-library track URIs

Mopidy media directories and scanning remain configured in `mopidy.conf`, not in `yoyopod_config.yaml`.
