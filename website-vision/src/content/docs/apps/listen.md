---
title: "Listen: Music & Stories"
description: Local-first music and stories — playlists, shuffle, now playing.
---

*The listening experience: the library, the wheel, and now playing.*

:::caution[Partially filled]
Sections marked *Placeholder* have no as-built content yet; everything else is condensed from the repository (see Sources at the bottom).
:::

## What it is

Listen is **local-first and local-only** — a recorded product decision, not
an accident. Music on yoyopod means files on the device, played by an
app-owned mpv backend over a filesystem library; streaming providers are
not active sources. Because the library lives on the device, playback works
with no internet. The cloud enters only as an *import* path: a track pushed
from the backend lands in the local library once and is an ordinary local
file from then on.

There is no store, no browsing feed, and no algorithm — only the library a
family builds. The family-facing view of listening lives at
[Listening](/families/listening/).

## Key flows

The Listen root opens a small local library menu — **Playlists**,
**Recent**, **Shuffle** (Artists and Albums views are deferred until the
local-first baseline is stable). Two UI primitives carry the whole
experience:

- **The wheel** for picking: the focused tile sits center-stage with dimmed
  peeks beside it; a press rolls one step with a spoken label, a
  double-press opens.
- **The arc hero** for now playing: artwork wrapped in a progress ring, one
  play chip, bare side glyphs.

Playlists are plain `.m3u` files, recents are recorded by the device itself
from track changes, and shuffle builds its queue from the files on disk.
The ritual this is built for: [Jonas's Saturday playlists](/stories/jonas-saturday-playlists/).

## On the device

Playback belongs to the [Media Engine](/builders/software/media-engine/):
a dedicated media worker in the Rust runtime, which
spawns and supervises an out-of-process **mpv** player over a JSON-IPC
socket — the rest of the system only sends work orders and reads state
snapshots. Details that protect the kid experience:

- Recents are capped at 50, and only files inside the music directory are
  recordable — a remote asset can't sneak into a child's history.
- Remote tracks are fetched into a bounded, checksum-verified local cache
  *before* mpv ever sees them, so playback always runs from a local file
  and a short-lived download link can't interrupt a song.
- Imported tracks persist in a dedicated uploads folder with their own
  playlist, indistinguishable from any other local music.

## In the parent app

*Placeholder — no as-built content yet.*

- Parents build the library from their phone: add music and stories, organize playlists (future)
- Sync model: how new content reaches the device over the cloud link (TBD)
- What parents can see about listening, and what they deliberately cannot (TBD)

## Status today

- Local playback works on the device: the media worker drives mpv on the
  prototype hardware, with playlists, recents, and shuffle in place.
- Remote playback has a **validated MQTT contract**: play, pause, resume,
  stop, and store-media commands with acks and lifecycle events, observed
  end-to-end on a real device — including the import that turns an uploaded
  track into an ordinary local file.
- The parent-app side of library management is future work — the app is not
  built yet.
- On the canvas, Listen is a current screen and becomes a wheel root in the
  v5 UI contract; the arc hero ships first as a simpler progress-bar
  fallback.

## Open questions

- TODO: How large can the local library be, and what happens at the storage limit?
- TODO: Do music and stories share one library view or split into two?

:::note[Sources]
Condensed from
[`docs/features/LOCAL_FIRST_MUSIC_PLAN.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/LOCAL_FIRST_MUSIC_PLAN.md)
and
[`docs/features/REMOTE_PLAYBACK.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/REMOTE_PLAYBACK.md)
and the as-built docs site (`website/` in the repository): the Screens &
Navigation page, the Local-First Music and Remote Playback feature pages,
and the media worker profile ("The Record Library").
:::
