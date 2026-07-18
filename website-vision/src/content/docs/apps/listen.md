---
title: "Listen: Music & Stories"
description: Local-first music and stories — playlists, shuffle, now playing.
---

*The listening experience: the library, the wheel, and now playing.*

:::caution[Vision stub]
Placeholder in the vision docs — the structure is decided, the content is
not written yet. As-built engineering docs live in the main docs site
(`website/` in the repository).
:::

## What it is

- Local-first music and stories: the library lives on the device, so playback works with no internet
- Parent-curated content only — no store, no browsing, no algorithmic feed
- Playlists, shuffle, and a calm now-playing view sized for the small glass
- The family-facing view of listening lives at [Listening](/families/listening/)

## Key flows

- Pick something: from the Hub wheel into Listen, scroll the library, play
- Now playing: what the glass shows, pause and resume with the side button
- Playlists and shuffle: how a kid moves between them (exact gestures TBD)
- A kid owning their own Saturday ritual: [Jonas's Saturday playlists](/stories/jonas-saturday-playlists/)

## On the device

- The Listen screen: one of the four on-device screens (Hub, Listen, Talk, Setup)
- Browsing a library on a roughly 240x280 portrait glass — list depth and artwork treatment (TBD)
- One physical side button: tap / double-tap / hold mapping while audio plays (TBD)
- Playback through the built-in speaker; headphone story (TBD)

## In the parent app

- Parents build the library from their phone: add music and stories, organize playlists (future)
- Sync model: how new content reaches the device over the cloud link (TBD)
- What parents can see about listening, and what they deliberately cannot (TBD)

## Status today

- The media worker exists on-device: a domain worker in the Rust runtime driving playback via mpv
- Local audio playback works on the prototype hardware
- Parent-app library management is future work — the parent app is not built yet
- Playlist and shuffle UX on the glass: structure decided, details open (TBD)

## Open questions

- TODO: How does content get onto the device before the parent app exists (transfer path, formats)?
- TODO: What are the side-button semantics while playing versus while browsing the library?
- TODO: How large can the local library be, and what happens at the storage limit?
- TODO: Do music and stories share one library view or split into two?
