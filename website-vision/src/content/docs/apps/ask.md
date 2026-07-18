---
title: "Ask: The Voice Companion"
description: Hold the button, ask a question, hear an answer — a voice companion, not a feed.
---

*The Ask experience — push-to-talk questions with spoken answers, disclosed as an AI-generated voice.*

:::tip[Proposed — the ideal design]
This page mixes as-built fact (covered by the Sources note) with the target
design, written out in full so it can be adopted, adapted, or dropped.
Everything marked *Proposed* is neither implemented nor committed.
:::

## What it is

Ask is the question-and-answer side of the companion. The child holds the button, asks something out loud — *"why is the sky blue?"* — lets go, and hears an answer spoken back. There is no feed to scroll, no follow-up bait, nothing on the canvas to linger over: one question, one answer, and the child can ask again or walk away. *Proposed:* the next step keeps exactly that shape and widens who answers — the Ask root screen becomes the **Ask wheel**, a wheel of parent-created **Help Agents** with the familiar companion voice as the default entry (see *Key flows* below).

The answer is spoken in an AI-generated voice, and that fact is not hidden: with cloud voice enabled, yoyopod is an AI-voice device and must be treated — and disclosed — as one. That disclosure obligation is stated in the repository's own runbook, and it travels with the feature everywhere Ask appears.

Positioning stays inside the refusals at [what we are not](/company/what-we-are-not/). Ask is one capability of the companion, sitting beside [Listen](/apps/listen/) and [Talk](/apps/talk/) — yoyopod is never marketed as AI for kids, and Ask does not change that.

## Key flows

*Proposed — the ideal design, not yet adopted.*

**The Ask wheel.** The child opens Ask and finds a wheel of Help Agents on the canvas. The yoyopod companion voice sits first on the wheel — it is always there, and for a fresh device it is the only entry. Around it appear the specialists a parent has summoned: "Math Helper", "Animal Expert", "Story Friend" — each one a name and a face on the wheel, nothing more. The child spins through them, lands on one, and the familiar loop takes over: hold the button, ask out loud, let go, hear the answer spoken back. Asking again stays with the same helper — the short conversational memory of a few turns lives inside that helper, so a follow-up about narwhals goes to the Animal Expert who just answered, not to a blank slate. Pressing Home leaves the conversation and returns to the wheel; the next visit starts fresh.

Each Help Agent answers in its own tone — playful, patient, or matter-of-fact, whichever the parent chose — but every one of them is the same disclosed AI-generated voice underneath, and the child-facing framing never pretends otherwise. Helpers answer questions; they never start conversations, never call out to the child, never nudge. The wheel waits until it is spun.

**What does not change.** Everything that makes Ask trustworthy today carries over unchanged. It is push-to-talk only — no helper is ever listening until the button is held. A new press cancels an answer in flight, so the child is never stuck listening. Quick push-to-talk commands from other screens ("play music", "make it louder") keep working exactly as before — the wheel only changes what happens inside Ask; see [using the button](/families/using-the-button/). The age-appropriate content policy is enforced in yoyocloud itself, not merely written into a prompt, so a cleverly-phrased question meets the same boundary as a plain one. And there are no ads, ever — no helper will ever mention a product, a show, or a place to spend money.

**When the cloud is away.** Offline, the Ask wheel degrades gracefully to Ask's existing offline state: the wheel is visible but resting, the device says honestly that it cannot answer right now, and every local control keeps working. Nothing is queued, nothing is recorded for later — the question simply waits until the child asks it again.

**Summoning a helper.** In [the yoyopod app](/apps/parent-app/), a parent taps *New Help Agent* and makes four choices: a **topic area** (math, science, animals, reading, and so on), a **tone** (playful, patient, or matter-of-fact), **boundaries** (what is off-limits for this helper), and a **name**. That is the whole ceremony — no scripting, no prompt-writing. The next time the device syncs, the new helper simply appears on the child's wheel, waiting to be discovered. It does not announce itself, because agents never initiate contact; the delight is the child finding it.

## On the device

Ask is one of the root screens in yoyocore's navigation stack, alongside the Hub, Listen, and Talk. The as-built Ask screen carries four states plus a dedicated offline state, and its normative mockup defines the input contract — what press, double-press, and long-press do in each state.

Behind the screen sits the speech worker, the interpreter of the Voice & Ask Engine — see the [Voice & Ask Engine](/builders/software/voice-ask/) page. It does three jobs: transcribe what the child said, fetch an answer, and synthesize the spoken reply — all as a pure translator between audio and cloud APIs. It holds a single conversation at a time: a second request while one is busy is refused and retried, matching the product reality that a child asks one thing at a time. Every request can be cancelled cooperatively — a new push-to-talk press ends the old one promptly — and every request honors a deadline, so the child is never left waiting on a hung answer. Answers themselves are kept deliberately short, with only a few turns of conversational memory.

The worker is optional and degrades gracefully. If it is disabled, or the cloud credentials are missing or invalid, cloud voice stops but local controls keep working — the Ask screen's offline state is the visible result, and the rest of the device carries on.

## In the parent app

*Proposed — the ideal design, not yet adopted.*

**Creating and configuring Help Agents.** The parent app is where helpers are born and shaped. Each Help Agent is those four choices — topic area, tone, boundaries, name — and each can be edited, paused, or removed at any time; changes reach the wheel on the next sync. The companion voice is the one entry parents do not manage: it is the default, always first on the wheel, and the way to remove it is to turn Ask off entirely. Boundaries deserve the most care in the app's design: they are stated in plain parent language ("no scary animal facts", "don't discuss weight or dieting"), and they are enforced in yoyocloud alongside the age-appropriate content policy — a boundary is a rule the service applies, not a polite request the helper might forget.

**Reviewing transcripts.** Parents can read what was asked and what was answered. The proposed default is a rolling 30-day retention window, controlled by the parent: shorten it, extend it, or clear it at any time. Retention and visibility are a genuine design choice, so the options are laid out:

| Option | What parents see | Trade-off |
| --- | --- | --- |
| **Full transcripts, 30-day parent-controlled retention (recommended)** | Every question and answer, per helper, for the window the parent sets | Real oversight of an AI voice talking to a child; the cost is some of the child's sense of a private companion |
| Summaries only | A periodic digest of topics asked about | Gentler on the child's privacy, but a parent cannot verify what was actually said |
| No visibility | Nothing | Strongest privacy stance, but no way to check the one feature that most needs checking |

**Recommendation: full transcripts with parent-controlled retention**, because when an AI-generated voice answers a child, verifiable oversight outranks the lighter options — and parent-controlled retention keeps that oversight bounded rather than becoming an archive. The child-facing honesty rule applies here too: families are encouraged to tell children that parents can see Ask conversations, in line with [privacy](/families/privacy/).

**Turning Ask off — and on.** Ask has a single master switch in [parental controls](/families/parental-controls/). Off means off: the wheel leaves the device's root screens, the speech worker goes idle, and quick button commands for local controls keep working. The default state is its own decision:

| Option | Behavior | Trade-off |
| --- | --- | --- |
| **Enabled at setup, companion only (recommended)** | The AI-voice disclosure is shown during [setup](/apps/setup/); the companion works out of the box; specialists are always parent-added | Disclosure happens at the moment of consent, and the first experience works — without any specialist appearing unrequested |
| Off until a parent enables it | Ask ships dark; the wheel appears only after an explicit opt-in | The safest-looking default, but many families would never discover the feature at all |

**Recommendation: enabled at setup with the disclosure in the flow**, because consent gathered at setup — with the AI voice plainly disclosed — is more honest than a buried toggle, and the companion-only start means nothing a parent didn't approve is ever on the wheel.

**Quiet hours (TBD).** A proposed later addition: windows when the wheel sleeps — bedtime, dinner, school hours. Whether this belongs to Ask specifically or to a device-wide schedule in parental controls is deliberately left open; see the decisions below.

## Status today

Ask exists and runs on the device today: the Ask screen is a current route, and the speech worker ships alongside the other workers. It requires the cloud link — Ask is a cloud-backed capability, configured per device through the lane environment, and without valid credentials it falls back to the offline state described above.

Validation is staged, not finished. The repository defines a manual smoke test (ask a question from the Ask screen, confirm the spoken answer, ask a follow-up, back out, confirm no stale answer, confirm quick commands still work), and automated on-device voice validation is explicitly paused pending a follow-up round. Nothing on this page should be read as "fully validated" until that flag is lifted.

## Open questions

- **Adopt or drop the Ask wheel.** Does Ask stay a single companion voice, or become the wheel of parent-created Help Agents described above? This is the page's central decision; everything else follows from it.
- **Transcript model.** Adopt full transcripts with 30-day parent-controlled retention (the recommendation), or choose the summaries-only middle ground and accept that parents cannot verify what was said?
- **Default state.** Ship Ask enabled at setup with the AI-voice disclosure in the flow (the recommendation), or dark until a parent explicitly switches it on?
- **Sequencing.** Gate specialist Help Agents on the yoyocloud-enforced content-policy and boundary layer being in place, or ship the wheel with the companion first and add specialists once enforcement lands?
- **Quiet hours.** Adopt as an Ask-level control, fold into a device-wide schedule in parental controls, or drop from V1 “Daylight” scope entirely?

:::note[Sources]
Condensed from [docs/features/CLOUD_VOICE_WORKER.md](https://github.com/attmous/yoyopod/blob/main/docs/features/CLOUD_VOICE_WORKER.md) and the as-built docs site (website/ in the repository): the screens and navigation page, the cloud voice worker runbook, and the speech interpreter profile.
:::
