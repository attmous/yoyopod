---
title: Parental Controls
description: Contacts, content, and time — what parents decide from the app.
---

*Every control a parent holds, in one place.*

:::tip[Proposed — the ideal design]
This page is the target design, written out in full so it can be adopted,
adapted, or dropped. Everything on it is proposed — neither implemented
nor committed.
:::

## What parents control

**Who can reach your kid.** The whitelist is the heart of it: the short list of people who can call the device, be called from it, and exchange voice notes with it. You build the list in the yoyopod app — add Grandma, name her, done — and nobody who isn't on it can reach the device at all. This isn't a filter that screens calls after they ring; the device itself refuses anything outside the list, and the wheel on the canvas only ever shows the people you approved. Even when the device has no signal, it keeps enforcing the last list it received — losing coverage never widens the circle. The everyday side of calling lives at [Talking](/families/talking/).

**Who answers your kid's questions.** [Ask](/apps/ask/) comes with one companion voice, and you can add Help Agents to its wheel — little specialists you create yourself. Making one takes exactly four choices: a topic area (animals, math, reading…), a tone (playful, patient, or matter-of-fact), boundaries (what this helper must never get into — "no scary stuff" is a perfectly good boundary), and a name. You can edit, pause, or remove any helper whenever you like; the change reaches the device on its next sync. Every helper speaks with the same clearly-disclosed AI-generated voice, and none of them ever starts a conversation — they only answer when your kid holds the button and asks.

**Whether Ask is on at all.** Ask has one master switch. Turn it off and the wheel of helpers leaves the device entirely — no question-answering, no AI voice, while music, stories, and calls carry on untouched.

**What was said.** You can read what your kid asked and what was answered, right in the app. Transcripts keep themselves for 30 days by default, and that window is yours to control: shorten it, or turn transcript storage off entirely. It's oversight, not surveillance — and we'd encourage you to tell your kid you can see Ask conversations, in the spirit of [our privacy promise](/families/privacy/).

**What's on the device.** Music and stories get onto the device through the app — you choose what's in the library, and it lives on the device itself, so [listening](/families/listening/) works with no internet at all. Removing something removes it; there is no store on the device and nothing a kid can download.

**Whether the map is on.** Live-ish location — the periodic, roughly-where dot described at [Location](/families/location/) — is a sharing choice you make, and you can turn it off. It is never a second-by-second track, on purpose.

## Where you set it

Everything lives in [the yoyopod app](/apps/parent-app/) on your phone — there is deliberately no settings maze on the device for a kid to wander into or a sibling to "help" with. The app has exactly five jobs: pairing, the whitelist, the live-ish location view, loading content, and building Help Agents. That's the whole control panel.

Changes travel one honest road: from your phone to our service, and from our service to the device over its own mobile connection — the app and the device never talk to each other directly. Because a device can be out of coverage when you make a change, the app always tells you the truth about where a change stands: **"saved"** means we have it and it will apply the moment the device next connects; **"active on device"** means the device has confirmed it's running your latest version. No guessing.

In a household with two parents, both accounts hold equal rights — either of you can edit the whitelist, manage helpers, or load content, and you both see the same state. Getting the app connected in the first place is covered at [The Parent App & Pairing](/families/parent-app-setup/).

## What kids can change themselves

Deliberately little — and that's a feature, not a limitation.

A kid decides what plays next from the library you loaded, calls anyone on the whitelist whenever they like, sends a voice note by holding the button, and turns the volume up or down. They can also rearrange the order of things on their wheel, so the playlist they love or the helper they've adopted sits first. That's their whole world of settings: the fun choices are theirs, the consequential ones are yours.

There is no menu on the canvas where a kid can add a contact, delete the library, or switch anything important off. Nothing they press can undo a decision you made — which means you never have to hover, and they never have to be careful.

## Open questions

- **Adopt or drop quiet hours for V1 “Daylight”** — scheduled windows when the device goes calm for school or sleep. If adopted: one device-wide schedule in parental controls, or a per-feature switch (Ask sleeps, calls stay)?
- **Adopt or drop a parent-set volume ceiling** — kids control volume freely today's design; is a hard upper limit a V1 control or a later refinement?
- **Adopt equal-rights households as the shipped V1 model**, or invest now in roles (owner vs. viewer) for separated households and grandparents?
- **Decide what the kid sees when a parent changes something** — silent updates keep the canvas calm, but a small "your grown-up added Grandma" moment might be kinder than things quietly appearing and disappearing.
