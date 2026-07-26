---
title: FAQ & Troubleshooting
description: Quick answers when something doesn't work.
---

*The questions every family asks, grouped for scanning.*

:::tip[Proposed — the ideal design]
This page is the target design, written out in full so it can be adopted,
adapted, or dropped. Everything on it is proposed — neither implemented
nor committed.
:::

## Setup & pairing

**What's in the box — do I need to buy a charger?**
The device, a USB-C charging cable, and a quick-start card. Honest caveat: the hardware today is the V0 “Dawn” prototype, so final box contents (including whether a wall brick is in there) aren't locked yet. The first ten minutes are walked through at [Unboxing](/families/unboxing/).

**Does the device need its own SIM or mobile plan?**
The device has its own mobile connection — that's how calls, voice notes, and the map work away from home, with nothing to install on the device itself. How that connection is activated and billed (bundled, or set up by you) is still being settled; this page will say so plainly once it's decided.

**The app can't find the device during pairing — what do I check?**
Here's the reassuring part: the app never searches for the device, so there's no finicky Bluetooth dance to fail. The device shows a short code on its little screen; you type or scan that code in the yoyopod app; our service checks the code and connects the device to your family. If the code isn't accepted: make sure the device is powered on and has mobile signal (pairing needs it to be online), ask the device for a fresh code if the one on screen has gone stale, and try again. The full walkthrough is at [The Parent App & Pairing](/families/parent-app-setup/).

**Can both parents — or a grandparent — connect to the same device?**
Yes. Parents share one household in the app, with equal rights: either of you can edit the whitelist, load content, or check the map, and you both see the same thing. A grandparent can join the household too if you want them to hold the controls — or, more commonly, simply be a whitelist contact who can call without managing anything. (Whether an app-less grandparent can also swap voice notes rides on an open decision — today's proposal delivers voice notes to the yoyopod app or another yoyopod; see [Talking](/families/talking/).)

**I got a new phone — how do I move the app over?**
Install the yoyopod app and sign in — your account uses a passkey, so there's no password to remember or reset. Everything (your household, whitelist, settings) lives in your account, not on the old phone, so nothing needs re-pairing and the device never notices you switched.

**Can the device be resold or handed down?**
Yes, and it's designed to be ordinary. Unclaim the device in the app: it's released from your household, wipes its local data, and becomes claimable again like new — ready for a younger sibling or its next family, carrying nothing of yours with it.

## Everyday use

**How long does the battery last on a school day?**
The honest answer, for now: it depends on the prototype. V0 “Dawn” hardware exists to learn from, and battery life varies build to build. The design goal is comfortably through a school day of listening and a few calls — but we won't print a number here until real devices in real backpacks have proven it.

**Does music really work with no internet at all?**
Really. Music and stories live on the device itself, so [listening](/families/listening/) works on the plane, in the basement, and in the dead zone behind the supermarket. No signal, no account, no problem — it plays.

**How do I add new music and stories, and how long until they're on the device?**
Loading content is one of the app's core jobs: pick what goes in the library, and it travels to the device over its mobile connection. How long that takes depends on coverage and file size — the app always shows you what's saved and what has actually arrived on the device, so there's no wondering.

**What do tap, double-tap, and hold do again?**
Tap moves one step around the wheel. Double-tap chooses what's in the middle. Hold steps back out — except on screens where the device listens (asking a question, recording a voice note), where hold means *talk*: hold, speak, let go, like a walkie-talkie. That's the entire interface; the five-minute version is at [Using the button](/families/using-the-button/).

**My kid says the button "didn't work" — what usually happened?**
Almost always timing: a hold released too soon, or a double-tap with too long a gap, so the device heard something different than intended. Occasionally the screen was simply asleep and the first press only woke it. The gesture timings are deliberately still being tuned by watching real kids' hands — if a gesture reliably misfires for your kid, that's exactly the feedback we want.

## Safety & privacy

**Why can nobody outside our whitelist call the device?**
Because the device itself refuses them. Only the contacts you approved exist on the calling wheel, and the calling machinery rejects anything from outside the list — two separate locks on the same door. It works even offline: the device keeps enforcing the last list it received, so losing signal never widens the circle. Managing the list is covered at [Parental controls](/families/parental-controls/).

**How fresh is the location on the map — is it real-time?**
No, and deliberately not. The map is *live-ish*: the device checks in periodically with a roughly-where position, and the app shows that dot with an honest timestamp. It answers "is she about where she should be?" without becoming minute-by-minute surveillance of a childhood. Trust the timestamp more than the dot — details at [Location](/families/location/).

**What data does the device collect, and where does it go?**
Very little, held briefly, hosted in the EU: a first name and an age band, your whitelist, periodic location fixes when you've enabled the map, and Ask transcripts kept 30 days by default — a window you can shorten or switch off. Music played on the device tells us nothing at all. The complete inventory, in parent words, is [Our Privacy Promise](/families/privacy/).

**Can strangers find or contact my kid through the device in any way?**
No. There is no public profile, no username, no directory, no discovery — nothing to search for. The only people who can reach the device are the ones you put on the whitelist, and the device won't accept anyone else even if they somehow had its number.

**Is the voice AI?**
Yes, and we say so plainly — during setup, in the app, and here. Answers on [Ask](/apps/ask/) are spoken by an AI-generated voice that never pretends to be a person, only speaks when your kid holds the button and asks, and never starts a conversation on its own. You can read every exchange in the app, and you can turn Ask off entirely.

**Is there really no camera, browser, or app store — and could one be added later?**
Really none, and no. There's no camera hardware to enable and no store for anything to arrive through — these are absences built into the physical device, not settings, so no software update can ever add them. What we've ruled out, and why, lives at [What we are not](/company/what-we-are-not/).

## Still stuck?

**Where do I reach support, and what should I have ready?**
The proposed launch setup is email support plus a report-a-problem button inside the yoyopod app (which sends your app version and device name along automatically, so you don't have to hunt for them). If you're writing email, mention the device's name from the app and roughly when the problem happened.

**How do I restart the device safely?**
With the one button: a long press-and-hold powers it down, and the same hold brings it back. (The exact hold duration is still being settled on prototype hardware.) Restarting is safe — music, stories, and settings all live on the device and survive it, and the whitelist re-syncs on its own.

**When is a restart the right move — and when isn't it?**
Restart when the device itself misbehaves: a frozen screen, silent audio, a button that's stopped responding. Don't bother restarting for things that travel over the network — a whitelist change not showing up yet, a stale dot on the map, content still on its way. Those are almost always coverage, and the fix is patience or a walk toward a window; the app's "saved" vs. "active on device" labels tell you exactly what's still in transit.

**How do I report a bug or suggest something?**
From the yoyopod app, in the proposed design — a short form that carries the technical details for you. Suggestions are genuinely wanted, especially in the prototype era: families notice things builders can't.

## Open questions

- **Adopt or trim the launch support channels** — email plus in-app reporting is the proposal; decide whether both exist at launch or email carries the first months alone.
- **Adopt this page as the single troubleshooting home**, or push fix-it answers onto each topic page ([Listening](/families/listening/), [Location](/families/location/), [Care](/families/care/)) with this page linking out — decide before pilot families arrive.
- **Adopt the "no battery number until measured" stance publicly**, or publish a target figure with a prototype disclaimer and accept the risk of being held to it.
- **Replace the guessed questions with real ones** — once pilot families exist, their actual top questions should reshape this page, and someone must own that review.
