---
title: "Ask: The Voice Companion"
description: Hold the button, ask a question, hear an answer — a voice companion, not a feed.
---

*The Ask experience — push-to-talk questions with spoken answers, disclosed as an AI-generated voice.*

:::caution[Partially filled]
Sections marked *Placeholder* have no as-built content yet; everything else is condensed from the repository (see Sources at the bottom).
:::

## What it is

Ask is the question-and-answer side of the companion. The child holds the button, asks something out loud — *"why is the sky blue?"* — lets go, and hears an answer spoken back. There is no feed to scroll, no follow-up bait, nothing on the canvas to linger over: one question, one answer, and the child can ask again or walk away.

The answer is spoken in an AI-generated voice, and that fact is not hidden: with cloud voice enabled, yoyopod is an AI-voice device and must be treated — and disclosed — as one. That disclosure obligation is stated in the repository's own runbook, and it travels with the feature everywhere Ask appears.

Positioning stays inside the refusals at [what we are not](/company/what-we-are-not/). Ask is one capability of the companion, sitting beside [Listen](/apps/listen/) and [Talk](/apps/talk/) — yoyopod is never marketed as AI for kids, and Ask does not change that.

## Key flows

*Placeholder — no as-built content yet.*

- The core loop step by step: hold to ask, release, listen to the answer.
- Follow-up questions without leaving the Ask screen — how far the short conversational memory reaches, and how it resets.
- How Ask coexists with quick push-to-talk commands ("play music", "make it louder") from other screens — see [using the button](/families/using-the-button/).
- Interrupting an answer: a new press cancels the one in flight.
- What the child sees and hears when the answer cannot come (the offline state).

## On the device

Ask is one of the root screens in yoyocore's navigation stack, alongside the Hub, Listen, and Talk. The as-built Ask screen carries four states plus a dedicated offline state, and its normative mockup defines the input contract — what press, double-press, and long-press do in each state.

Behind the screen sits the speech worker, the interpreter of the Voice & Ask Engine — see the [Voice & Ask Engine](/builders/software/voice-ask/) page. It does three jobs: transcribe what the child said, fetch an answer, and synthesize the spoken reply — all as a pure translator between audio and cloud APIs. It holds a single conversation at a time: a second request while one is busy is refused and retried, matching the product reality that a child asks one thing at a time. Every request can be cancelled cooperatively — a new push-to-talk press ends the old one promptly — and every request honors a deadline, so the child is never left waiting on a hung answer. Answers themselves are kept deliberately short, with only a few turns of conversational memory.

The worker is optional and degrades gracefully. If it is disabled, or the cloud credentials are missing or invalid, cloud voice stops but local controls keep working — the Ask screen's offline state is the visible result, and the rest of the device carries on.

## In the parent app

*Placeholder — no as-built content yet.*

- Enabling or disabling Ask for a child from the yoyopod app.
- Visibility for parents: whether questions and answers surface as transcripts, summaries, or not at all.
- Where the disclosure of the AI-generated voice lives in the parent-facing setup flow — see [setup](/apps/setup/) and [the parent app](/apps/parent-app/).

## Status today

Ask exists and runs on the device today: the Ask screen is a current route, and the speech worker ships alongside the other workers. It requires the cloud link — Ask is a cloud-backed capability, configured per device through the lane environment, and without valid credentials it falls back to the offline state described above.

Validation is staged, not finished. The repository defines a manual smoke test (ask a question from the Ask screen, confirm the spoken answer, ask a follow-up, back out, confirm no stale answer, confirm quick commands still work), and automated on-device voice validation is explicitly paused pending a follow-up round. Nothing on this page should be read as "fully validated" until that flag is lifted.

## Open questions

- Parent controls: should Ask be off by default until a parent enables it in the yoyopod app, and can it be scheduled or limited?
- Transcript policy: do parents see what was asked and answered, and how does that square with the child's sense of a private companion?
- Disclosure surface: beyond the repository-level obligation, where exactly does the AI-voice disclosure appear for the child and for the parent?
- When does the paused automated on-device voice validation resume, and what does "validated" mean for spoken answers?

:::note[Sources]
Condensed from [docs/features/CLOUD_VOICE_WORKER.md](https://github.com/attmous/yoyopod/blob/main/docs/features/CLOUD_VOICE_WORKER.md) and the as-built docs site (website/ in the repository): the screens and navigation page, the cloud voice worker runbook, and the speech interpreter profile.
:::
