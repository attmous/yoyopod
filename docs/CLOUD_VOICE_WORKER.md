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
```

For the prod lane, use `/etc/default/yoyopod-prod` instead.

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
