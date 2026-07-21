---
title: "Listen: Music & Stories"
description: Local-first music and stories — playlists, shuffle, now playing.
---

*The listening experience: the library, the wheel, and now playing.*

:::tip[Proposed — the ideal design]
This page mixes as-built fact (covered by the Sources note) with the target
design, written out in full so it can be adopted, adapted, or dropped.
Everything marked *Proposed* is neither implemented nor committed.
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

*Proposed — the ideal design, not yet adopted.*

Content loading is one of the yoyopod app's five V1 “Daylight” jobs, and it
works the way a parent would hope: pick something, and it shows up on the
device. From the device view in [the yoyopod app](/apps/parent-app/), a
parent adds audio — music the family already owns, stories they pick out or
purchase — and the app hands it to yoyocloud, which delivers it to the
device over the device's own link. The app and the device never talk
directly; yoyocloud is always in between, which is why loading works the
same whether the yoyopod is on the kitchen shelf or at grandma's for the
weekend.

Once delivered, a track is an ordinary local file — the import path
described under [On the device](#on-the-device) — so everything a parent
loads keeps playing with no internet at all. If the device is offline when
the parent adds something, the delivery simply waits: the app shows the
content as **saved**, and marks it **on the device** once the yoyopod has
fetched it. No spinners to babysit, no failed transfers to retry — the
plumbing catches up on its own.

The app also shows the library as the device sees it: which playlists,
music, and stories are actually on the yoyopod, and roughly how much room
is left. What the app deliberately does not show is a listening log.
Parents decide what goes on the device; what a kid plays, and how often,
stays the kid's own — the same restraint described at
[Privacy](/families/privacy/).

**Remote start — the bedtime flow.** One small, warm exception to "the app
is for parents, the device is for kids": a parent can start a story on the
device from their phone. Pick the story in the app, tap play, and it begins
on the yoyopod's speaker across the room — the flow
[Bedtime stories](/stories/bedtime-stories/) is built on. Under the hood it
rides the same validated remote-playback contract as content delivery, and
on the device it behaves like any other playback: the kid can pause it,
skip it, or turn it off with the button, because the device is theirs.

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

- **Adopt a storage budget with a visible gauge?** The app showing "how
  much room is left" implies a decided cap and a decided behavior at the
  limit — nothing should ever silently delete a kid's music, so the honest
  option is a full-library message that asks the parent to remove
  something.
- **Adopt one library or two?** Music and stories could share one view or
  split in two — on the wheel and in the app both. Splitting reads better
  at bedtime; sharing is simpler. Decide once, before the app's library
  screens are designed.
- **Adopt remote start in V1, or defer it?** It rides the already-validated
  remote-playback contract, so the cost is app UI, not device work — but it
  sits just beyond the five-job scope and should be admitted as an
  exception knowingly if adopted.
- **Adopt the no-listening-log stance as permanent?** Parents see what is
  on the device, never what was played and when — a values decision worth
  writing down before anyone asks for the chart.

:::note[Sources]
Condensed from
[`docs/features/LOCAL_FIRST_MUSIC_PLAN.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/LOCAL_FIRST_MUSIC_PLAN.md)
and
[`docs/features/REMOTE_PLAYBACK.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/REMOTE_PLAYBACK.md)
and the as-built docs site (`website/` in the repository): the Screens &
Navigation page, the Local-First Music and Remote Playback feature pages,
and the media worker profile ("The Record Library").
:::
