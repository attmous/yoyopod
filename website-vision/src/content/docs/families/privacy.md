---
title: Our Privacy Promise
description: What data exists, where it lives, and who can see it.
---

*The plain-language privacy promise a parent can actually read.*

:::tip[Proposed — the ideal design]
This page is the target design, written out in full so it can be adopted,
adapted, or dropped. Everything on it is proposed — neither implemented
nor committed.
:::

## Our promises

**We know almost nothing about your kid, on purpose.** A child's profile in our service is a first name and an age band. Not a birthday, not a photo, not a school, not a surname. If a piece of information isn't needed to make the device work, we don't collect it — and the best answer we can ever give to "what do you store about my child?" is "we never stored that."

**Everything lives in Europe.** All of our service's data is hosted in the EU, under GDPR — the strictest tier of it, because this is children's data. That isn't a legal posture we adopted reluctantly; it's the standard the product is built to.

**What we do keep, we keep briefly.** Location fixes are held for a short window and then gone. Ask transcripts keep themselves for 30 days by default — and you can shorten that or turn transcript storage off entirely in [parental controls](/families/parental-controls/). Nothing about your child accumulates into an archive.

**The map is live-ish, never a track.** Location is a periodic, roughly-where check-in — a dot with an honest timestamp, not a breadcrumb trail. The app never pretends the dot is fresher than it is, and there is no minute-by-minute history to scroll back through. More at [Location](/families/location/).

**The microphone opens only while the button is held.** Push-to-talk is the only way audio ever leaves the device — hold, speak, release, like a walkie-talkie. There is no wake word, no "hey yoyopod," no always-listening mode, and there never will be. This is a permanent commitment, not a current setting.

**The voice is AI, and we say so.** When the device answers a question, that answer is spoken by an AI-generated voice, and we disclose that plainly — during setup, in the app, and to you here. It never pretends to be a person, and parents can read what it said at any time.

**No ads. Ever.** Not on the canvas, not in an answer, not whispered into a story. There is no advertising in this product and no version of this product in which there will be.

**Leaving is clean.** Unclaim a device in the app and it's truly let go: our service unbinds it from your household, the device wipes its local data, and it becomes claimable again like new. Hand-me-downs and resale are ordinary, not a loophole — see the [FAQ](/families/faq/).

## What data exists and where it lives

Here is the complete inventory, in parent words:

**The child profile** — a first name and an age band. Held by our service so the app can say "Mia's yoyopod" and so answers can be pitched to the right age. That's the whole file.

**The whitelist** — the contacts you approved, with the names you gave them. You edit it in [the yoyopod app](/apps/parent-app/); our service holds the master copy and the device keeps a synced copy so it can enforce the list even with no signal. It exists to protect your kid, and only you can change it.

**Live-ish location** — when you've turned it on, the device reports a periodic, coarse position. The app shows the latest dot and when it arrived; fixes are kept only briefly and then deleted.

**Ask transcripts** — what your kid asked and what was answered, kept 30 days by default so you can look, with the window yours to shorten or switch off. When it's off, questions are answered and not kept.

**Voice notes and calls** — calls happen live and are not recorded. Voice notes pass through our service only to be delivered to whitelisted family — queued while a phone or device is offline, handed over when it reconnects — not collected into a library on our side.

**The content library** — the music and stories you loaded live on the device itself and play with no internet at all. What your kid listens to on the device is the device's business, not ours: local listening produces nothing for us to know.

**Your parent account** — secured with a passkey rather than a password, so there's nothing to phish and nothing to reuse. It holds what it must to run the household: your sign-in, your devices, your settings.

## What we never do

- **No ads, no selling, no sharing.** Your family's data is not a product. It is never sold, rented, or shared with data brokers — there is no "partners" paragraph coming later.
- **No feed, no followers, no streaks.** Nothing on the canvas is engineered to be checked, chased, or kept up. The device is built to be put down.
- **No listening in.** The microphone serves the held button — calls, voice notes, and questions — and nothing else. Not us, not "quality purposes," not anyone.
- **No public identity for your kid.** No profile, no username, no discovery. A stranger cannot find, follow, or contact this device, because there is nothing to search for and no door for them to knock on. Only the whitelist reaches your kid.
- **No camera, no browser, no app store.** Whole categories of risk removed in hardware — and hardware can't be updated into existing.
- **No pretending.** The AI voice is disclosed as AI. The map is called live-ish because it is. If a plain-language page like this one ever leaves you unsure what a setting does, that's our bug, and we mean that literally.

## Open questions

- **Publish the numbers, or keep them policy?** Committing publicly to EU hosting, the 30-day transcript default, and a concrete location-retention window builds trust — and binds us. Decide whether these become printed promises or internal standards.
- **Voice notes in transit** — adopt a fixed maximum queue-and-delete window for undelivered notes, and decide whether delivered notes leave any trace on our side at all.
- **Location history** — commit to "latest fix only, nothing to scroll back through," or allow a short parent-visible history and accept the retention question that comes with it.
- **Account deletion end to end** — design the one-button "delete everything" flow for a parent's full account (devices unclaimed, transcripts gone, profile erased) and decide what confirmation it shows so a parent can trust it happened.
