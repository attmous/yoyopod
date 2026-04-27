# Cloud Voice Worker

This document covers the dev/prod environment needed to run the Go cloud voice
worker with OpenAI STT/TTS.

The API key is a device secret. Do not commit it to repo config files.

## OpenAI Setup

For the dev lane, edit the systemd environment file on the Pi:

```bash
ssh rpi-zero
sudo touch /etc/default/yoyopod-dev
sudo chgrp "$USER" /etc/default/yoyopod-dev
sudo chmod 640 /etc/default/yoyopod-dev
sudoedit /etc/default/yoyopod-dev
```

Add or update these lines:

```bash
OPENAI_API_KEY=sk-...
YOYOPOD_VOICE_MODE=cloud
YOYOPOD_VOICE_WORKER_ENABLED=true
YOYOPOD_VOICE_WORKER_PROVIDER=openai
YOYOPOD_STT_BACKEND=cloud-worker
YOYOPOD_TTS_BACKEND=cloud-worker
YOYOPOD_CLOUD_TTS_MODEL=gpt-4o-mini-tts
YOYOPOD_CLOUD_TTS_VOICE=coral
YOYOPOD_CLOUD_TTS_INSTRUCTIONS="Speak warmly and calmly for a child. Use simple words, friendly pacing, and brief answers. Avoid scary emphasis."
YOYOPOD_CLOUD_ASK_MODEL=gpt-4.1-mini
YOYOPOD_CLOUD_ASK_TIMEOUT_SECONDS=12
YOYOPOD_CLOUD_ASK_MAX_HISTORY_TURNS=4
YOYOPOD_CLOUD_ASK_MAX_RESPONSE_CHARS=480
```

For the prod lane, use `/etc/default/yoyopod-prod` instead.

OpenAI requires disclosure that TTS output is AI-generated. YoYoPod should be
treated as an AI voice device whenever cloud TTS is enabled.

The file is group-readable because the remote dev workflow sources lane
defaults as the SSH deploy user before systemd starts the root-owned service.
Do not make this file world-readable.

After editing the environment file, restart the active lane:

```bash
sudo systemctl restart yoyopod-dev.service
```

or for prod:

```bash
sudo systemctl restart yoyopod-prod.service
```

## Verify Configuration

Check that the service started and that the worker health probe passed:

```bash
systemctl is-active yoyopod-dev.service
journalctl -u yoyopod-dev.service -n 120 --no-pager | grep -E "Cloud voice worker|voice worker"
```

Expected log line:

```text
Cloud voice worker ready: provider=openai
```

If the key is missing or invalid, the app degrades the cloud voice backend and
keeps local controls usable.

## Ask App Smoke Test

1. Open Ask from the hub, not quick PTT.
2. Ask "why is the sky blue?"
3. Confirm the screen shows an answer and the speaker uses the configured cloud voice.
4. Tap/select Ask again and ask "what is rain?"
5. Confirm the second answer works without leaving Ask.
6. Press Back or hold Back and confirm Ask exits and no stale answer plays.
7. Use quick PTT for "call mama", "play music", and "make it louder" to confirm commands still use command mode.

## Live Worker Smoke Test

From the Pi checkout, source the lane environment and run the worker with the
OpenAI provider:

```bash
cd /opt/yoyopod-dev/checkout
/opt/yoyopod-dev/venv/bin/python -m yoyopod_cli.main build voice-worker
set -a
. /etc/default/yoyopod-dev
set +a
YOYOPOD_VOICE_WORKER_PROVIDER=openai \
  workers/voice/go/build/yoyopod-voice-worker
```

The worker reads newline-delimited JSON command envelopes on stdin and writes
JSON envelopes on stdout. For normal hardware validation, prefer the app-level
smoke route:

```bash
yoyopod pi validate stability
```

or from the dev machine:

```bash
uv run yoyopod remote --host rpi-zero --branch <branch> validate --sha <commit>
```
