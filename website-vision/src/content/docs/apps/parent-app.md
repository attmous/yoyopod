---
title: The Parent App
description: "The companion mobile app: contacts, content, controls."
---

*The parent's side of yoyopod: everything managed from one phone app.*

:::tip[Proposed — the ideal design]
This page mixes as-built fact (covered by the Sources note) with the target
design, written out in full so it can be adopted, adapted, or dropped.
Everything marked *Proposed* is neither implemented nor committed.
:::

## What it is

*Proposed — the ideal design, not yet adopted.*

**The yoyopod app** is one phone app for everything a parent does:
contacts, content, controls, and reassurance. It ships on **iOS and
Android** from day one, because a household with one iPhone parent and
one Android parent is the normal case, not the edge case. Kids hold the
device; parents hold their phone — and the app is the buyer-facing half
of the product, built so that parents manage and kids simply use.

The app never talks to the device directly. Everything flows through
[yoyocloud](/builders/software/cloud/), the backbone in the middle —
which is why a change made from the office applies just as reliably as
one made from the sofa, and why the app works identically whether the
phone and the device share a room or a country.

It is a companion, not a mirror. The app does not replay what the
device does — it does not stream the kid's music or show a copy of
their screen. It manages: who can call, what is loaded, where the
device roughly is, and which Help Agents live on the
[Ask wheel](/apps/ask/). A parent creates each Help Agent with exactly
four choices — a topic area, a tone, boundaries, and a name — and the
app is where transcripts can be reviewed afterward.

The scope for V1 “Daylight” is deliberately narrow: five jobs, done
well — pairing, whitelist management, the live-ish location view,
content loading, and the Help Agent builder. The experience it all must
add up to is [a parent's first week](/stories/first-week-parent/):
calm, legible, and finished in minutes rather than evenings.

## Key flows

*Proposed — the ideal design, not yet adopted.*

**Pairing a new device.** The device shows a short code on its canvas;
the parent types it into the app or scans it; yoyocloud checks that
this device is really showing that code right now and binds it to the
household. No cable, no local network dance, no Bluetooth roulette —
the same three steps whether it is a brand-new device or a hand-me-down
being claimed afresh. The full walkthrough lives at
[setup from the parent side](/families/parent-app-setup/).

**Contacts — the whitelist.** The parent builds the list of people the
device can call and trade voice notes with: add a name and number,
remove one, done. The device only ever knows the people on this list —
there is no dial pad to bypass it. After every edit the app shows two
honest states: **saved** (the change is safely stored) and **active on
device** (the device has confirmed it is now living by it). If the
device is off or out of coverage, the parent sees the truth — saved,
and it will apply the moment the device next connects. The family-facing
story is at [parental controls](/families/parental-controls/).

**Content — loading the library.** Parents put music and stories onto
the device from the app: pick albums and story collections, press load,
and they travel down to the device's local library. Once loaded, they
play with no internet at all — a road trip or a dead spot never
silences [bedtime stories](/stories/bedtime-stories/).

**Location — the live-ish glance.** The app shows where the device
last reported and exactly when, and nothing more — no live feed, no
route history. The full experience, including kid-initiated check-ins,
is at [Locate](/apps/locate/).

**The Help Agent builder.** Four choices — topic area, tone,
boundaries, name — and the new helper appears on the device's Ask
wheel. All Help Agents speak with one shared voice that is always
disclosed as AI-generated; none of them ever starts a conversation.
The builder is also where a parent reviews transcripts of what was
asked and answered — kept for 30 days by default, and the parent can
shorten that or turn it off entirely.

## On the device

*Proposed — the ideal design, not yet adopted.*

The kid never sees the app — they see its effects, and the effects are
small good news. A new name appears on Talk's contact wheel: Grandma
can call now. A new album shows up in Listen: someone was thinking of
you. A new helper joins the Ask wheel: there is now a patient voice
that knows about dinosaurs. Changes arrive quietly, without
interrupting whatever is playing.

The division of control is simple: the app owns every decision that
belongs to the family — who is on the whitelist, what content is
loaded, which Help Agents exist, how location behaves. The device
itself keeps only what a kid should adjust in the moment — volume, and
deliberately little else; there is no settings menu on the canvas
([Setup](/apps/setup/) is one-time onboarding, not a control panel), so
nothing safety-relevant can be undone on the device.

Offline behavior is the same story everywhere: an app-made change is
saved immediately and applies when the device next connects, and the
app never pretends otherwise. Meanwhile the device keeps enforcing the
last list of contacts it was given — going out of coverage never means
going out of bounds, and never means losing music or stories, which
live on the device itself.

## In the parent app

*Proposed — the ideal design, not yet adopted.*

The app is organized around the device, not around features. A parent
opens it and sees their child's yoyopod, front and center: battery,
whether it is connected right now, and the timestamp of the last
location fix or check-in. One glance answers the background question —
*is everything okay over there?* — before a single tap.

Everything else hangs off that device view: **Contacts** (the
whitelist), **Library** (music and stories to load), **Location** (the
live-ish map), and **Helpers** (the Help Agent builder and transcript
review). No dashboard sprawl, no analytics, no engagement charts — the
app is a place to take care of something and then put the phone down.

Households are shared. Two parents each sign in with their own account,
see the same devices, and hold equal rights — in V1 there are no roles,
no owner-versus-viewer tiers, no permission matrix to administer. A
change either parent makes shows up for the other, marked plainly. A
family with two kids and two yoyopods sees two device cards, each with
its own whitelist, library, and helpers.

## Status today

The app itself does not exist yet — but the device side it will talk to is
ready in places, and the build order is deliberate: device first, so the
app lands on a cloud link that already works.

- The device-side cloud link runs today: a provisioned device holds a
  device id and secret, connects over MQTT on per-device topics (events,
  acks, commands), publishes heartbeat, battery, and connectivity
  telemetry, and queues messages while offline.
- One backend-to-device contract is **validated on hardware**: remote
  playback — play, pause, resume, stop, and store-media commands with
  acks and lifecycle events — including importing an uploaded track into
  the device's local library.
- The claiming, household, and parent flows are owned by the backend and
  dashboard; the device never talks to the dashboard directly, it
  consumes provisioned secrets and the command channel.
- Not everything is wired yet: HTTP/REST sync, location telemetry, and
  richer backend command types are configured or backend-supported but
  not fully built — the intended surface, not the current one.

## Open questions

- **Adopt both stores at launch?** iOS and Android on day one is the design intent, because mixed-platform households are the norm — confirm it, or consciously stage one platform first and accept excluding half of most couples.
- **Adopt the five-job V1 scope as a hard cap?** Pairing, whitelist, live-ish location, content loading, Help Agent builder — every addition delays the date a real family can use the device.
- **Adopt equal-rights households for V1?** Two parents, one household, identical powers — simple and honest, but it defers separated-family and guardian-role questions to V2 on purpose.
- **Adopt saved-versus-active as the universal pattern?** Showing both states for every change is more honest and slightly more complex than a single "done" — commit to it everywhere, or nowhere.

:::note[Sources]
Condensed from
[`docs/features/REMOTE_PLAYBACK.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/REMOTE_PLAYBACK.md)
and
[`docs/features/CLOUD_PROVISIONING_AND_BACKEND.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/CLOUD_PROVISIONING_AND_BACKEND.md)
and the as-built docs site (`website/` in the repository): the Remote
Playback and Cloud Provisioning & Backend feature pages.
:::
