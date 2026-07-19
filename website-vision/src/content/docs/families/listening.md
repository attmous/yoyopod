---
title: "Listening: Music & Stories"
description: Local-first music and stories, playlists, and the now-playing flow.
---

*Everyday listening: what plays, how kids choose it, and how parents load it.*

:::tip[Proposed — the ideal design]
This page mixes as-built fact (covered by the Sources note) with the target
design, written out in full so it can be adopted, adapted, or dropped.
Everything marked *Proposed* is neither implemented nor committed.
:::

## What you'll need

*Proposed — the ideal design, not yet adopted.*

Not much: a paired device, and [the yoyopod app](/apps/parent-app/) on a
parent's phone. Loading content is one of the app's core jobs — a parent
picks music and stories in the app and taps to send them, and the next
time the device is on and connected, they arrive quietly on their own.
Once a track has landed, it lives on the device as an ordinary file, and
from that moment playback needs no internet at all. The app is honest
about the difference between *sent* and *arrived*: it shows what is
already on the device and what is still on its way, so you are never
left guessing whether the bedtime story made it in time for bedtime.

## Steps

From the home wheel, tap over to [Listen](/apps/listen/) and double-tap
in. Listen is itself a small wheel with three choices today:
**Playlists**, **Recent**, and **Shuffle**. (Browsing by artist or album
is deliberately deferred until this simple version is solid.)

- **Playlists** are lists of tracks stored on the device itself.
- **Recent** is remembered by the device on its own — the last things
  that played, kept short, kept on the device.
- **Shuffle** mixes everything in the library.

Double-tap a choice and the **now-playing view** takes over: the artwork
sits center stage with a ring around it that fills as the track plays,
and one play/pause control. The full ring treatment is still rolling
out — on today's devices it may appear as a simple progress bar instead.

The most important thing about Listen: **it works with no internet at
all**. Music and stories live on the device as ordinary files and play
from there — the tunnel, the basement, and the forest all work fine.
This is a deliberate product decision, not a limitation: streaming
services are intentionally not part of Listen.

One honest note for now: **there is no parent app yet.** Today, music
and playlists are loaded onto the device by the development team working
directly with it. The load-from-your-phone flow this page's outline
describes is where things are headed, not where they are.

## Tips

*Proposed — the ideal design, not yet adopted.*

Build the library together: the kid picks, the parent loads. The best
libraries on these devices are small and loved, not large and ignored —
and a kid who chose the songs owns the ritual that plays them.

Make playlists for moments, not just moods: stories for
[bedtime](/stories/bedtime-stories/), the loud one for Saturday morning
([Jonas has opinions](/stories/jonas-saturday-playlists/)), a short one
for the walk to school. On a wheel with no search box, a well-named
playlist *is* the interface.

Load before the trip, not during it. Getting new content onto the device
needs the device online once; playing it never does. Ten minutes of
loading the night before a holiday buys two weeks of tunnel-proof,
ferry-proof, middle-of-nowhere-proof listening.

## Troubleshooting

*Proposed — the ideal design, not yet adopted.*

**"Nothing to play."** The device starts empty and stays empty until a
parent loads it — an empty library is a to-do in the yoyopod app, not a
fault on the device.

**Sent from the phone, but not on the device.** New content arrives the
next time the device is on and connected — check the app, which shows
for each item whether it has landed or is still on its way. A device in
a drawer with a flat battery receives nothing; charge it, switch it on,
and the library catches up by itself.

**A song stopped mid-play.** It is never coverage — playback is local,
so the tunnel is innocent. Check the battery first: the device warns
when it is low and switches itself off safely when it is nearly empty
(see [Charging & Care](/families/care/)).

**Too quiet or too loud.** Volume is adjusted on the device itself, not
from the app — worth a minute of practice together, so the kid can fix
it alone the first time it happens on a bus.

## Open questions

- Adopt the yoyopod app as the only way content reaches the device, or also ship a small starter set of music and stories in the box so the first hour is never silent?
- Adopt parent-only curation — kids choose what plays, parents choose what is loaded — or give kids on-device favoriting and reordering?
- Adopt a visible storage gauge in the app that declines new loads gracefully at the limit, or handle capacity silently and hope it is never hit?
- One library or two: do music and stories share a single view on the canvas, or split into separate wheels?

:::note[Sources]
Condensed from
[`docs/features/LOCAL_FIRST_MUSIC_PLAN.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/LOCAL_FIRST_MUSIC_PLAN.md)
and the as-built docs site (website/ in the repository): the Local-First
Music feature page and the UI guide's navigation page (Screens &
Navigation).
:::
