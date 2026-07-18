---
title: Media Engine
description: "Local-first playback under yoyocore: the media worker, mpv, and the playback contract."
---

*The platform capability behind Listen — local files, one playback engine, one owner.*

## Overview

The Media Engine is one of the four peer engines of the software platform, alongside the UI Engine, the Calling Engine, and the Voice & Ask Engine (see [the architecture](/builders/software/architecture/)). It owns everything that makes sound *from files*: the local music library, playlists, recent tracks, remote-asset caching and import — and the whole lifecycle of an out-of-process mpv player. The rest of yoyocore never touches mpv directly; it sends `media.*` work orders and reads back state snapshots.

The engine is built on a deliberate product decision: **Listen is local-first and local-only.** Spotify, Amazon Music, and other streaming providers are not active Listen sources, and must not be treated as active sources unless a separate, explicit decision reverses that. Music on yoyopod means on-device files, played by an app-owned mpv backend over a filesystem library — which is why the library works with no internet at all.

yoyocloud enters only as an *import* path, never a streaming path. The product experience this powers is described at [Listen](/apps/listen/).

## Key components

**The media worker.** A dedicated worker binary (`yoyopod-media-host`, roughly 2,750 lines) supervises mpv. Its configuration is pushed, not read: it waits for a `media.configure` command that the runtime composes from `audio/music.yaml` and `device/hardware.yaml`. It spawns mpv with `--idle --no-video --input-ipc-server=…` routed to the configured ALSA device, talks to it over mpv's JSON-IPC Unix socket, and observes seven mpv properties (title, metadata, pause, idle-active, duration, path, time-position), translating property changes into playback state. Startup retries the IPC connection for up to 10 seconds or until the mpv process dies — whichever comes first.

**mpv, app-owned.** mpv is the single playback engine — spawned and supervised by the media worker, never a separate daemon. The division of labor is clean: mpv does playback, state, progress, and push events; the worker does library scanning, playlist discovery, recents, shuffle, and the one-button experience. The install contract on the yoyoOS image is two system packages: `mpv` itself and `alsa-utils` for device inspection and audio smoke testing. From mpv outward, the signal path through the amplifier and speaker is covered under [audio hardware](/builders/hardware/audio/).

**The library.** Playlists are plain `.m3u` files discovered anywhere under the configured music directory. Recents are a JSON store capped at 50 entries, recorded by yoyocore itself from mpv track-change events — and only URIs inside the music directory are recordable, so a streamed remote asset can't sneak into a child's history. Shuffle builds its queue from filesystem track paths, and metadata falls back to local tag reads when mpv's metadata is sparse.

**The remote-asset cache.** Tracks pushed from yoyocloud land in a bounded LRU disk cache (SHA-256 verified where checksums are provided, 512 MiB default, 32 MiB floor, path-sanitized). Imported tracks are persisted into a `dashboard_uploads/` folder in the music directory, plus a `Dashboard Uploads.m3u` playlist — after which they are ordinary local files like any other.

## Interfaces & contracts

**The device-side command surface.** The media worker exposes 21 commands and 6 events — the largest command surface of any worker in yoyocore. Commands group into lifecycle (`configure`, `start`, `stop`, `health`, `shutdown`), transport (`play`, `pause`, `resume`, `stop_playback`, `next_track`, `previous_track`), library (`load_tracks`, `load_playlist`, `list_playlists`, `list_recent_tracks`, `shuffle_all`, `play_recent_track`), remote (`prepare_remote_asset`, `import_remote_asset`), and audio (`set_volume`, `set_audio_device`). Events are `media.ready`, `media.snapshot`, `media.track_changed`, `media.playback_state_changed`, `media.backend_availability_changed`, and `media.error`. Time-position updates deliberately emit no event of their own — the snapshot carries progress.

**The remote playback contract.** yoyocloud can drive playback and import media over MQTT through a fully specified command/ack/event contract, validated end-to-end on real hardware. Five commands are accepted: `play_track`, `pause`, `resume`, `stop`, and `store_media`. A strict separation rule holds: `ack` carries command acceptance only, `evt` carries lifecycle only — an ack or nack is never replayed as a lifecycle event. Playback lifecycle states are `buffering`, `playing`, `paused`, `stopped`, `completed`, and `failed`; import lifecycle is `imported` or `failed`.

**Playback always runs from a local file.** Remote tracks are fetched into the cache *before* mpv ever sees them — never played from the signed backend URL — so short token lifetimes can't interrupt a song. Downloads run off the coordinator thread, and a just-fetched asset is protected from immediately evicting itself even when the cache is over cap.

Session behavior is defensive by design: one active remote session at a time, with a new valid `play_track` interrupting the current one; pending downloads correlated by command ID and activation generation so a stale stop can't clear the *next* session; a `stop` during buffering discards the pending asset so playback never starts after a stop was acked; and duplicate command IDs acked as duplicates, never replayed.

**The `store_media` import path.** yoyocloud finalizes an uploaded household track, sends `store_media` over the same dispatcher, the device downloads it through the same cache path, persists it under `dashboard_uploads/`, updates the playlist, and emits `media_library.imported` (or `failed`). The backend stays the policy authority; the result surfaces as ordinary local files in Listen. This is the import path that keeps local-first honest.

**What the engine does *not* own.** The pause-music-during-a-call behavior is not in the Media Engine — it is a routing policy in the runtime (see [the runtime](/builders/software/runtime/)). The Media Engine knows nothing about telephones. And a defensive detail worth knowing: an `end-file` from mpv with any reason other than `eof` clears the current track, so a crash mid-song doesn't leave a ghost "now playing".

## Today vs. target

**Working today.** The local library end to end: `.m3u` playlists, recents, shuffle, mpv supervision over JSON-IPC, and volume and device control — all functioning with no internet connection. The remote playback and import contract has been validated on hardware: the full sequence of ack → buffering → playing → paused → resume → stop, plus `store_media` → `imported` and cached-asset replays, was observed end-to-end on a real device. (One operational note from that validation run: the device image logged VoIP recovery warnings from an unavailable Liblinphone backend; it does not affect playback or import.)

**Deferred.** The Listen root today opens a small local library menu — Playlists, Recent, Shuffle. Artists and Albums views are deferred until the local-first baseline is stable; they are not built yet.

**Not planned without an explicit reversal.** Streaming providers as active Listen sources. The local-first decision (dated 2026-04-07) stands unless a separate, explicit product decision reverses it.

## Open questions

- The canonical mpv dependencies doc names the audio device as `hw:1`, while the config and the hardware-verified audio stack route through `alsa_device: default` (card 0, `wm8960-soundcard`). The verified route wins, but the canonical doc still needs correcting.
- What concretely marks the local-first baseline as "stable" enough to unlock the deferred Artists and Albums views?
- Is the 512 MiB remote-asset cache cap right once household uploads accumulate, or does eviction pressure need revisiting?
- mpv's Unix-socket IPC is unix-only, with no Windows path — is that an accepted constraint for developer workflows, or does it need a documented alternative?

:::note[Sources]
Condensed from [`docs/features/LOCAL_FIRST_MUSIC_PLAN.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/LOCAL_FIRST_MUSIC_PLAN.md), [`docs/features/MPV_DEPENDENCIES.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/MPV_DEPENDENCIES.md), and [`docs/features/REMOTE_PLAYBACK.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/REMOTE_PLAYBACK.md), and the as-built docs site (website/ in the repository): the media worker page, Local-First Music, MPV Dependencies, and Remote Playback.
:::
