---
title: "Talk: Calls & Voice Notes"
description: Contact-first calling and quick voice messages, whitelist only.
---

*The talking experience: contacts first, whitelist always, one button to speak.*

:::caution[Vision stub]
Placeholder in the vision docs — the structure is decided, the content is
not written yet. As-built engineering docs live in the main docs site
(`website/` in the repository).
:::

## What it is

- Whitelist-only calls and voice messages: kids reach the people parents approved, nobody else
- Contact-first: names on the glass, never a number pad, never an unknown caller
- Quick voice notes as the everyday default; live calls for the moments that need them
- The family-facing view of talking lives at [Talking](/families/talking/)

## Key flows

- Call a favorite: from the Hub wheel into Talk, pick a contact, call — [Grandma calls](/stories/grandma-calls/)
- Send a voice note: hold the side button to talk, release to send — [a voice note from the bus](/stories/voice-note-from-the-bus/)
- Receive: what an incoming call or voice note looks and sounds like (TBD)
- Missed things: how a kid finds and replays a waiting voice note (TBD)

## On the device

- The Talk screen: a short contact list sized for the small portrait glass
- The single side button: hold doubles as push-to-talk; tap and double-tap inside Talk (TBD)
- Built-in speaker and microphone — hands-free by design
- Clear audible and visible cues while a call is active (TBD)

## In the parent app

- Parents manage the whitelist: add, remove, and name contacts (future)
- Contact changes reach the device over the cloud link (TBD)
- What parents see about call activity, and what stays between kid and contact (TBD)

## Status today

- The voip worker exists: a domain worker in the Rust runtime dedicated to calling
- End-to-end call validation is still staged — full device-to-phone calls are being proven out
- Voice-note flow: outlined, not yet implemented end to end (TBD)
- Whitelist management waits on the parent app (future work)

## Open questions

- TODO: What is the exact push-to-talk grammar (hold to record, release to send, how to cancel)?
- TODO: When does the device ring — always, quiet hours, parent-scheduled windows?
- TODO: Where do voice notes queue when the device is offline, and for how long?
