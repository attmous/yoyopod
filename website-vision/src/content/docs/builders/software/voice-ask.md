---
title: Voice & Ask Engine
description: "Push-to-talk speech under yoyocore: the speech worker, cloud STT/TTS, and the Ask experience's engine."
---

*The platform capability behind Ask — hold the button, speak, hear an answer.*

:::tip[Proposed — the ideal design]
This page mixes as-built fact (covered by the Sources note) with the target
design, written out in full so it can be adopted, adapted, or dropped.
Everything marked *Proposed* is neither implemented nor committed.
:::

## Overview

The Voice & Ask Engine is the platform layer behind the [Ask experience](/apps/ask/): the child holds the side button, speaks, and hears an answer. It is strictly push-to-talk — speech capture happens only while the [held button](/families/using-the-button/) says so; there is no wake word and no always-on microphone. Under yoyocore it lives as one worker among the [engine peers](/builders/software/architecture/), owning the spoken-language work: transcription (STT), synthesis (TTS), and Ask — the question-and-answer behind the Ask screen. It is a pure translator between WAV files and cloud APIs; capture and playback hardware belong to other workers.

One naming trap to carry with you: the crate and binary say **speech** (`device/speech/`, `yoyopod-speech-host`), but the wire domain is **`voice.*`** (`voice.transcribe`, `voice.ask`, …). When searching the codebase, search both.

One obligation to carry with you: TTS output is AI-generated. With cloud TTS enabled, the device speaks with an AI-generated voice and must be treated — and disclosed — as such.

## Key components

**The speech worker** (`yoyopod-speech-host`, roughly 1,400 lines of Rust) is configured by environment only — no YAML, no configure command; per-request parameters ride in each command payload. It selects its provider via `YOYOPOD_VOICE_WORKER_PROVIDER`: `mock` for tests and CI, or `openai` for the real thing, calling `/v1/audio/transcriptions` (`gpt-4o-mini-transcribe`), `/v1/audio/speech` (`gpt-4o-mini-tts`), and `/v1/responses` (`gpt-4.1-mini`) over TLS.

**The cloud configuration** lives in the systemd lane environment file (`/etc/default/yoyopod-dev` or `-prod`), group-readable but never world-readable. The `OPENAI_API_KEY` is a device secret — environment only, never committed to repository config. Tunables cover models, the TTS voice, speaking-style instructions ("Speak warmly and calmly for a child…"), Ask timeouts, history turns, and response length caps.

**The Ask screen** is the UI-visible face of the engine — four states plus an explicit offline state. The worker is optional: with it disabled, the domain reads `Disabled` and the Ask screen shows its offline state. Likewise, if the API key is missing or invalid, cloud voice degrades gracefully while local controls keep working. Offline never breaks the device; it just closes the Ask door politely.

## Interfaces & contracts

The worker speaks newline-delimited JSON envelopes on stdin/stdout — the same wire as every other worker. Its command set is `voice.health`, `voice.transcribe`, `voice.speak`, `voice.ask`, `voice.cancel`, and `voice.shutdown`; results and events mirror them (`voice.ready`, `voice.transcribe.result`, `voice.ask.result`, `voice.cancelled`, `voice.error`, …). Error codes: `invalid_payload`, `provider_error` (retryable), `busy`, `protocol_error`, `invalid_kind`, `unknown_command`.

The contract encodes the product reality that a child asks one thing at a time:

- **One in-flight request.** A second command while busy returns a retryable `busy` error.
- **Cooperative cancellation.** `voice.cancel` — or a new push-to-talk press — flips a flag the work loop checks every 10 ms; a cancelled request returns promptly even though the underlying HTTP call finishes detached.
- **Deadlines honored.** The envelope's `deadline_ms` is respected — this is the only worker that does.
- **Guardrails on audio.** Transcription enforces `max_audio_seconds` by parsing the WAV header (with a conservative byte-cap fallback), so a runaway recording is refused, not billed. TTS responses arrive with streaming RIFF sizes, which the worker rewrites to real lengths so downstream players don't choke.

## Today vs. target

Today, with a key configured, cloud STT, TTS, and Ask work end-to-end: the documented smoke test opens Ask from the hub, asks "why is the sky blue?", confirms the answer in the configured voice, asks a follow-up, and verifies quick PTT command mode still works alongside. Honest status flag: **automated on-device voice validation is paused** until the Round-2 follow-up — hardware validation is currently a deploy-and-watch-the-logs exercise, not a gate.

The target keeps the same shape — push-to-talk in, spoken answer out — with the validation gap closed and the experience polish tracked on the [Ask page](/apps/ask/).

### Model strategy

*Proposed — the ideal design, not yet adopted.*

Today the engine is OpenAI-backed through a single environment key, and the model names are tunables, not an abstraction — swapping providers means rewriting the worker's cloud path. The proposed target puts a thin provider abstraction inside the engine's cloud path so STT, TTS, and the Ask model can each be chosen independently, per cost and per safety. The gate for any swap is not price alone: every candidate model must first pass a kid-appropriateness test set — a fixed battery of child-voiced questions, boundary probes, and tone checks (contents TBD) — before it can serve a single family. The abstraction is deliberately boring: same `voice.*` wire contract, same one-in-flight discipline, different HTTP shapes behind it. The device never learns which provider answered; that decision lives in configuration, where [yoyocloud](/builders/software/cloud/) can steer it.

### Wake word and hands-free interaction

*Proposed — the ideal design, not yet adopted.*

The proposed decision is explicit, and it closes this placeholder permanently: **no always-listening, ever.** No wake word, no hands-free capture, no "hey yoyopod" — not as a roadmap item, not as an experiment, not in any version. Push-to-talk is not a stopgap awaiting a better microphone strategy; it is the design. The [held button](/families/using-the-button/) is the only key that opens the microphone, and the [privacy promise](/families/privacy/) to families depends on that sentence staying true without asterisks. The recommendation is to record this as a permanent commitment in [principles](/company/principles/) rather than leaving it an open slot that every future planning meeting has to re-litigate.

### The Help Agent registry

*Proposed — the ideal design, not yet adopted.*

The Ask root screen becomes the **Ask wheel**: a wheel of **Help Agents**. The default entry is the yoyopod companion voice; parents add specialists. The kid spins the wheel, picks a helper, holds the button, and asks — curiosity-driven answers, spoken back. This section is the engine-side home of that idea; the family-facing story lives on the [Ask page](/apps/ask/) and in the [yoyopod app](/apps/parent-app/).

The engine-side insight is that a Help Agent is not code — it is configuration. An agent profile holds exactly the four parent choices: a name, a **topic area** (math, science, animals, reading, …), a **tone** (playful, patient, matter-of-fact), and **boundaries** (what is off-limits). Every helper speaks with the same disclosed AI-generated voice underneath — a per-agent voice is deliberately not part of the profile. Parents author profiles in the yoyopod app; yoyocloud stores them as part of the family's configuration and syncs them to the device the same way every other piece of configuration arrives. The Voice & Ask Engine does not grow a new pipeline: each profile becomes system context layered over the same STT → model → TTS path the engine already runs. On the wire, the selected agent's profile id rides in the `voice.ask` payload exactly like the per-request parameters that already ride there — no new commands, no new worker.

Where the profile turns into model context is a real choice:

| Option | What it means | Trade-off |
| --- | --- | --- |
| On the device, in yoyocore | Profiles sync down; the device assembles the prompt | Prompt logic ships in firmware; every safety fix is a device update |
| **In yoyocloud, at request time** | The device sends audio + profile id; yoyocloud assembles context and enforces policy | Policy and prompts evolve server-side; the device stays the pure translator it already is |
| In the yoyopod app, at authoring time | The full prompt is baked into the profile when the parent saves it | Brittle — behavior pins to whatever app version the parent last opened |

**Recommendation: in yoyocloud, at request time** — it keeps the device a thin translator (which it already is, as-built) and lets safety and prompt improvements reach every family without a firmware release.

The wheel itself is a contract with the [UI Engine](/builders/software/ui/): agents appear as wheel entries on the canvas, and every focus change speaks the label aloud — voice carries pre-readers, so a five-year-old who cannot read "Animals" hears it. When the device is offline, the Ask wheel degrades gracefully to its offline state, exactly as the Ask screen does today; the wheel never pretends a helper is available when the cloud is not.

One positioning guard, stated here because engineers write marketing copy by accident: Help Agents feed curiosity. They do not make yoyopod an educational device or "AI for kids," and the refusal list at [what we are not](/company/what-we-are-not/) stands unamended.

### The safety layer

*Proposed — the ideal design, not yet adopted.*

The safety design rests on one principle: a prompt is a suggestion; a policy check is a gate. Every safety property below is enforced in [yoyocloud](/builders/software/cloud/), not merely written into an agent's system context.

**Content policy in yoyocloud.** Every Ask request and every generated answer passes a server-side, age-appropriate content policy check — regardless of which Help Agent is selected and regardless of what its prompt says. An agent's parent-set boundaries ("no scary stuff", "skip anything about weight") are compiled into that same server-side policy, so a clever question cannot talk its way past them. If a model swap ever weakens prompt adherence, the gate still holds; that is the whole point of not trusting the prompt alone.

**Transcripts, parent-controlled.** Parents can review what was asked and answered in the yoyopod app — oversight is part of the [parental controls](/families/parental-controls/) story, not a surveillance afterthought. Retention is a genuine choice:

| Option | What it means | Trade-off |
| --- | --- | --- |
| No transcripts stored | Audio and text discarded after the answer | Maximum privacy; parents fly blind on what their child is being told |
| **30 days, parent-controlled** | Default 30-day retention; parents can shorten it or turn it off | Real oversight without yoyocloud becoming a childhood archive |
| Indefinite until deleted | Everything kept until a parent acts | An ever-growing record of a child's questions is a liability, not a feature |

**Recommendation: 30 days, parent-controlled** — long enough for a parent to notice a pattern, short enough that the record expires by default.

**The standing invariants.** These are design commitments, not tunables: push-to-talk only, never always-listening (the [decision above](#wake-word-and-hands-free-interaction), aligned with the [privacy promise](/families/privacy/)); the AI-generated voice is always disclosed to families — during [setup](/apps/setup/) and in the yoyopod app, not only in builder docs; Help Agents never initiate contact — the device speaks only after the child holds the button; and there are no ads, ever, in any Ask answer or anywhere near one. Enforcement mechanics — key handling, transport, and the policy service boundary — belong with the rest of the [security posture](/builders/software/security/).

## Open questions

- **Adopt or drop the Ask wheel and Help Agent registry** as the Ask root screen — the single largest product decision on this page, and it commits the yoyopod app, yoyocloud, and the UI Engine simultaneously.
- **Adopt the permanent "no always-listening, ever" commitment** and record it in [principles](/company/principles/), closing the wake-word placeholder for good — or keep it an open slot.
- **Adopt the 30-day parent-controlled transcript default**, or choose one of the other retention stances before any transcript is ever stored.
- **Adopt provider abstraction plus the kid-appropriateness test set** as the precondition for any model change — or accept single-provider dependence as a deliberate simplification.
- **Unify or declare permanent the speech/`voice.*` naming split** — either rename the crate to match the wire, or write the trap into the docs as canon and stop revisiting it.

:::note[Sources]
Condensed from [`docs/features/CLOUD_VOICE_WORKER.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/CLOUD_VOICE_WORKER.md) and the as-built docs site (website/ in the repository): the speech worker profile, the cloud voice worker runbook, and the screens and navigation page.
:::
