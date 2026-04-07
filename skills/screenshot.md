---
name: screenshot
description: Capture a screenshot of the app's display from Raspberry Pi
disable-model-invocation: true
allowed-tools:
  - Read
  - Bash(uv run python scripts/pi_remote.py:*)
argument-hint: "[--readback]"
---

## Config

Use `deploy/pi-deploy.yaml` as the single source of truth for Raspberry Pi connection, PID, and screenshot settings. `scripts/pi_remote.py` reads this file directly.

If the file does not exist, stop and tell the user to create it.

## Argument Parsing

Parse the arguments string provided after `/screenshot`:

- **--readback flag:** If `--readback` is present, use LVGL readback. Otherwise use the shadow buffer.

## Steps

1. **Capture the screenshot to a temporary local PNG.** Run:
   ```bash
   uv run python scripts/pi_remote.py screenshot [--readback] --output <local_temp_path>
   ```
   Use a temporary local path such as `./pi_screenshot.png`.

2. **Display the PNG.** Use the agent's local image viewing tool to show the saved screenshot in the conversation.

3. **Explain what was captured.** After showing the image:
   - Default mode: "This is the shadow buffer - what the app sent to the display."
   - `--readback`: "This is the LVGL readback - what LVGL actually rendered."

   Remind the user they can ask follow-up questions about what they see, such as "why is the status bar missing?" or "what screen is this?"

4. **Clean up.** Delete the temporary local screenshot file after displaying it.
