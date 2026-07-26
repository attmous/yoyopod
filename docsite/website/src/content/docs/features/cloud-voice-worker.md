---
title: Cloud Voice Worker
description: Setting up the cloud STT/TTS/Ask worker — the environment file, the variables, and the smoke tests.
---

The runbook for enabling cloud voice — the OpenAI-backed STT/TTS/Ask
behind the Ask screen. The worker itself is documented in
[the interpreter profile](/runtime/workers/speech/); this page is the
setup and verification path.

:::danger[The API key is a device secret]
Never commit it to repo config. And note the disclosure obligation: TTS
output is AI-generated — with cloud TTS enabled, yoyopod is an AI-voice
device and must be treated (and disclosed) as one.
:::

## Setup: the lane environment file

Configuration lives in the systemd lane defaults — `/etc/default/
yoyopod-dev` (dev) or `/etc/default/yoyopod-prod` (prod). The file must
be group-readable for the deploy user but **not world-readable**:

```bash
sudo touch /etc/default/yoyopod-dev
sudo chgrp "$USER" /etc/default/yoyopod-dev
sudo chmod 640 /etc/default/yoyopod-dev
sudoedit /etc/default/yoyopod-dev
```

Key variables:

| Variable | Example |
| --- | --- |
| `OPENAI_API_KEY` | `sk-…` |
| `YOYOPOD_VOICE_MODE` | `cloud` |
| `YOYOPOD_VOICE_WORKER_ENABLED` | `true` |
| `YOYOPOD_VOICE_WORKER_PROVIDER` | `openai` |
| `YOYOPOD_STT_BACKEND` / `YOYOPOD_TTS_BACKEND` | `cloud-worker` |
| `YOYOPOD_CLOUD_TTS_MODEL` / `_VOICE` | `gpt-4o-mini-tts` / `coral` |
| `YOYOPOD_CLOUD_TTS_INSTRUCTIONS` | "Speak warmly and calmly for a child…" |
| `YOYOPOD_CLOUD_ASK_MODEL` | `gpt-4.1-mini` |
| `YOYOPOD_CLOUD_ASK_TIMEOUT_SECONDS` | `12` |
| `YOYOPOD_CLOUD_ASK_MAX_HISTORY_TURNS` / `_MAX_RESPONSE_CHARS` | `4` / `480` |

Apply with `sudo systemctl restart yoyopod-dev.service`. If the key is
missing or invalid, cloud voice degrades but local controls keep
working — the Ask screen's offline state is the visible result.

## Verify

```bash
systemctl is-active yoyopod-dev.service
journalctl -u yoyopod-dev.service -n 120 --no-pager | grep -E "voice worker"
# expected: Cloud voice worker ready: provider=openai
```

## The Ask smoke test

Open Ask from the hub (not quick PTT) → ask *"why is the sky blue?"* →
confirm the answer in the configured voice → ask a second question
without leaving Ask → confirm → back out and verify no stale answer →
then use quick PTT ("play music", "make it louder") to confirm command
mode still works alongside.

## Driving the worker directly

The binary ships in the CI artifact with the other workers. From the Pi
checkout:

```bash
set -a; . /etc/default/yoyopod-dev; set +a
YOYOPOD_VOICE_WORKER_PROVIDER=openai device/speech/build/yoyopod-speech-host
```

It speaks newline-delimited JSON envelopes on stdin/stdout — the same
[wire](/runtime/protocol/) as everything else. Preferred hardware
validation: `yoyopod target deploy`, then
`yoyopod target logs --follow --filter speech`.

:::note[Canonical source]
Condensed from
[`docs/features/CLOUD_VOICE_WORKER.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/CLOUD_VOICE_WORKER.md).
(The canonical doc's "Go worker" phrasing is stale — the binary is the
Rust `yoyopod-speech-host`.) Automated on-device voice validation is
paused until the Round-2 follow-up — see the [Roadmap](/product/roadmap/).
:::
