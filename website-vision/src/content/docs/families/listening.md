---
title: "Listening: Music & Stories"
description: Local-first music and stories, playlists, and the now-playing flow.
---

*Everyday listening: what plays, how kids choose it, and how parents load it.*

:::caution[Partially filled]
Sections marked *Placeholder* have no as-built content yet; everything else is condensed from the repository (see Sources at the bottom).
:::

## What you'll need

*Placeholder — no as-built content yet.*

- A paired device with some music or stories loaded by a parent
- The parent app for managing the library (loading flow TBD)
- No internet required for playback — the library lives on the device

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

*Placeholder — no as-built content yet.*

- Local-first means the tunnel, the basement, and the forest all work fine
- Build playlists together — the kid picks, the parent loads
- Stories at bedtime, music on the way to school: playlists per moment
- Volume limits and listening-time expectations (parent-side controls TBD)

## Troubleshooting

*Placeholder — no as-built content yet.*

- "Nothing to play" — the library is empty until a parent loads it
- A playlist changed on the phone but not on the device yet (sync timing TBD)
- Sound too quiet or too loud — where volume is controlled (device vs. app, TBD)
- Playback stops unexpectedly — battery, sleep, or quiet-hours behavior (TBD)

## Open questions

- TODO: Where does the content come from — parent uploads, bundled catalogs, or both?
- TODO: How and when does the library sync from the parent app to the device?
- TODO: Is there a maximum library size on the device, and how is it communicated?
- TODO: Can kids reorder or favorite tracks on-device, or is curation parent-only?

:::note[Sources]
Condensed from
[`docs/features/LOCAL_FIRST_MUSIC_PLAN.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/LOCAL_FIRST_MUSIC_PLAN.md)
and the as-built docs site (website/ in the repository): the Local-First
Music feature page and the UI guide's navigation page (Screens &
Navigation).
:::
