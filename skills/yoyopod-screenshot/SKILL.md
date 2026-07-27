---
name: yoyopod-screenshot
description: Capture a screenshot of the active yoyopod display from Raspberry Pi
disable-model-invocation: true
allowed-tools:
  - Read
  - Bash(yoyopod target:*)
argument-hint: "[--readback]"
---

## Config

Use `deploy/pi-deploy.yaml` as the shared deploy contract and
`deploy/pi-deploy.local.yaml` for machine-specific overrides such as
host, SSH user, dev lane checkout, and branch. Screenshots target the
currently running lane; dev normally runs from `/opt/yoyopod-dev/checkout`,
and prod runs from `/opt/yoyopod-prod/current`. `yoyopod target` merges
the config files directly.

If the file does not exist yet, run `yoyopod target config edit` first.
That command creates `deploy/pi-deploy.local.yaml` automatically before
opening it.

## Argument Parsing

Parse the arguments string provided after `/yoyopod-screenshot`:

- **--readback flag:** If `--readback` is present, request LVGL
  readback. Otherwise use the shadow buffer.

## Steps

1. **Check lane state.**
   ```bash
   yoyopod target mode status
   ```

2. **Capture the screenshot to a temporary local PNG.** Run:
   ```bash
   yoyopod target screenshot [--readback] --out <local_temp_path>
   ```
   Use a temporary local path such as `./pi_screenshot.png`.

3. **Display the PNG.** Use the agent's local image viewing tool to show
   the saved screenshot in the conversation.

4. **Explain what was captured.** After showing the image:
   - Default mode: "This is the shadow buffer — what the app sent to
     the display."
   - `--readback`: "This is the requested LVGL readback path — what
     LVGL actually rendered if the native snapshot succeeded."

   Remind the user they can ask follow-up questions about what they
   see, such as "why is the status bar missing?" or "what screen is
   this?"

5. **If the user is debugging screenshot fidelity, verify the capture
   path in logs.** Run:
   ```bash
   yoyopod target logs --lines 20
   ```
   Confirm one of these outcomes:
   - `Saved screenshot via LVGL readback` means the readback path succeeded.
   - `Saved screenshot via shadow buffer` means the capture used the
     shadow path instead.

6. **Clean up.** Delete the temporary local screenshot file after
   displaying it.
