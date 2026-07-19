---
title: "Jonas, 10: Saturday Playlists"
description: A morning of music that works with no internet at all.
---

*Jonas and a Saturday morning of music, offline in the garden.*

:::tip[Proposed — the ideal design]
This page is the target design, written out in full so it can be adopted,
adapted, or dropped. Everything on it is proposed — neither implemented
nor committed.
:::

## The moment

Saturday, nine in the morning. Jonas is ten, and he is heading to the
back of the garden with a plan involving pallet wood, a length of rope,
and no adults. He takes exactly one piece of technology with him:
yoyopod.

The back of the garden is a connectivity dead zone — behind the shed,
past the compost, the signal bars on any phone give up entirely. Jonas
does not know this and would not care. He taps the side button, the
canvas wakes, and he spins the wheel to [Listen](/apps/listen/). There
is his Saturday playlist, right where it always is. One press, and the
first song comes out of the speaker while he drags the first pallet into
position.

Two hours later there is something in the corner of the garden that is
recognizably a fort, and a boy inside it who has been singing along on
and off the whole time. When he comes in for lunch, sawdust in his hair,
the battery has barely noticed the morning.

## What yoyopod does

Every song Jonas heard this morning lives *on the device*. Not cached,
not buffered, not streamed on a good day — stored, as files, the way
music used to simply be somewhere. So the dead zone behind the shed made
no difference at all: no internet was involved at any point between his
thumb pressing the button and the speaker playing.

The Listen wheel gives him his whole world in three moves: his
playlists, his recent tracks, and shuffle — a spin and a press each.
When a song is playing, the canvas shows the now-playing view: the track
name, and a bright arc creeping around the round edge of the canvas as
the song moves along — a glance tells him where he is in the song, and a
glance is all it asks for.

What Jonas does not have is just as deliberate. There is no feed. There
is no autoplay sliding him from his playlist into someone's algorithm.
There are no ads, no thumbnails, no "up next." The playlist his parents
loaded is the whole universe, and it turns out a universe curated by
people who love you is plenty. When the playlist ends, it ends — the
speaker goes quiet, and Jonas, hammering, notices the birds have been
singing the whole time.

## Behind the scenes

This is the [Media Engine](/builders/software/media-engine/) doing what
it was built for, and it was built on one sentence: Listen is local-first
and local-only. The music library is a folder of ordinary audio files on
the device; playlists are plain playlist files discovered inside it;
shuffle builds its queue from the actual files on disk; recents are
remembered on the device itself. Playback is handled by a single
battle-tested audio engine that the Media Engine supervises as its own
private worker — the rest of the system just sends it "play this" and
reads back "here's where we are."

Offline is not a fallback mode the device drops into — it is the
default the device never leaves. Music arrives beforehand: parents load
it through the yoyopod app, it travels once through yoyocloud to the
device, and from that moment on it is an ordinary local file like every
other, with no further need for a connection, an account, or anyone's
permission. How that loading works from a parent's side is described at
[Listening](/families/listening/).

## Why it matters

This is the local-first pillar made concrete: the fun does not depend on
coverage, on a subscription being reachable, or on any server having a
good day. Behind the shed is exactly as good a place to listen as the
living room.

For Jonas, the music is *his* — on his device, in his pocket, wherever
he goes, the same songs in the same order every time he wants them.

For his parents, there is no streaming account attached to a child, no
recommendation engine deciding what plays after the song they approved,
and no bill that quietly makes the music stop.

And it is the light-touch idea in practice: two hours of use this
morning, and maybe ninety seconds of it spent looking at the canvas.
The rest was music, pallet wood, and birds. More Saturdays like this
one live at [Stories](/stories/).

## Open questions

- **Loading paths:** adopt the yoyopod app as the only way music gets onto the device in V1 — one path, one mental model — or add a desktop/USB transfer path alongside it for big libraries and accept two stories to support?
- **On-device curation:** adopt parent-curated-only (Jonas plays what is there; arranging it is a parent job in the app), or give him a small on-device gesture — a favorite, a reorder — and accept the extra surface on the canvas?
- **Storage honesty:** adopt a fixed on-device music allowance with a published, honest hours-of-audio figure families can plan around, or leave capacity unstated until the hardware numbers settle?
- **Headphones:** adopt speaker-first with a simple wired-headphone option for shared spaces, or ship speaker-only in V1 and defer the headphone story entirely?
