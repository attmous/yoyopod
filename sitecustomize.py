"""Process-wide Python startup tweaks for the YoyoPod repo."""

from __future__ import annotations

import os

# Keep CLI help and setup commands from printing pygame's support banner before
# our own command output.
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
