"""Regression guard: the legacy Go voice worker has been removed.

Runtime, deploy, CI, and active tests must use the Rust speech host.
Historical docs may still describe the old migration path.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ACTIVE_PATHS = (
    ".github/",
    "config/",
    "deploy/",
    "scripts/",
    "tests/",
    "workers/",
    "yoyopod_cli/",
    "device/",
)
PATTERNS = (
    "workers/voice/go",
    "go-voice-worker",
    "yoyopod-voice-worker",
    "voice-go",
)


def _is_self_reference(path: str) -> bool:
    return path.replace("\\", "/") == "tests/cli/test_no_go_voice_worker_references.py"


def test_no_active_go_voice_worker_references() -> None:
    unexpected: list[str] = []
    for pattern in PATTERNS:
        result = subprocess.run(
            ["git", "grep", "-l", pattern, "--", *ACTIVE_PATHS],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode not in (0, 1):
            raise AssertionError(f"git grep failed for {pattern!r}: {result.stderr}")
        for path in result.stdout.splitlines():
            if path.strip() and not _is_self_reference(path.strip()):
                unexpected.append(f"{path.strip()}: {pattern}")

    assert not unexpected, (
        "Legacy Go voice worker references remain in active code paths. "
        "Use Rust speech-host instead.\n"
        + "\n".join(sorted(unexpected))
    )
