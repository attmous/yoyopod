---
title: Voice & Ask Engine
description: "Push-to-talk speech under yoyocore: the speech worker, cloud STT/TTS, and the Ask experience's engine."
---

*The platform capability behind Ask — hold the button, speak, hear an answer.*

:::caution[Partially filled]
Sections marked *Placeholder* have no as-built content yet; everything else is condensed from the repository (see Sources at the bottom).
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

### Wake word and hands-free interaction

*Placeholder — no as-built content yet.*

- Nothing wake-word-like or always-listening exists in the repository, and nothing of the sort is promised.
- Any future exploration would have to be tested against [what we are not](/company/what-we-are-not/) first — see Open questions.

## Open questions

- Always-listening capture likely conflicts with the privacy promise outright — does the wake-word placeholder above deserve a permanent "no", recorded in [principles](/company/principles/), rather than an open slot?
- Where should the AI-generated-voice disclosure surface for families — setup, the yoyopod app, the device itself — beyond the builder docs stating the obligation?
- Automated on-device voice validation is paused (Round-2 follow-up): what guards against cloud-voice regressions until it resumes?
- The naming split — crate says *speech*, wire says `voice.*` — is documented as a trap; should it eventually be unified, or declared permanent?

:::note[Sources]
Condensed from [`docs/features/CLOUD_VOICE_WORKER.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/CLOUD_VOICE_WORKER.md) and the as-built docs site (website/ in the repository): the speech worker profile, the cloud voice worker runbook, and the screens and navigation page.
:::
