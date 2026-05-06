"""Small process memory snapshot helpers for Pi diagnostics."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProcessMemorySnapshot:
    """Best-effort memory snapshot for one process."""

    pid: int
    rss_kb: int | None
    pss_kb: int | None
    private_dirty_kb: int | None
    source: str


def collect_process_memory(
    *,
    pid: int | None = None,
    proc_root: Path = Path("/proc"),
) -> ProcessMemorySnapshot:
    """Return PSS/RSS when Linux procfs exposes it, else a safe unavailable snapshot."""

    actual_pid = os.getpid() if pid is None else int(pid)
    proc_dir = proc_root / str(actual_pid)
    smaps_path = proc_dir / "smaps_rollup"
    status_path = proc_dir / "status"

    smaps_text = _safe_read_text(smaps_path)
    if smaps_text is not None:
        return parse_smaps_rollup(smaps_text, pid=actual_pid)

    status_text = _safe_read_text(status_path)
    if status_text is not None:
        return ProcessMemorySnapshot(
            pid=actual_pid,
            rss_kb=parse_status_rss_kb(status_text),
            pss_kb=None,
            private_dirty_kb=None,
            source="status",
        )

    return ProcessMemorySnapshot(
        pid=actual_pid,
        rss_kb=None,
        pss_kb=None,
        private_dirty_kb=None,
        source="unavailable",
    )


def parse_smaps_rollup(text: str, *, pid: int) -> ProcessMemorySnapshot:
    """Parse the memory fields used by the runtime architecture spec."""

    values = _parse_kb_fields(text)
    return ProcessMemorySnapshot(
        pid=pid,
        rss_kb=values.get("Rss"),
        pss_kb=values.get("Pss"),
        private_dirty_kb=values.get("Private_Dirty"),
        source="smaps_rollup",
    )


def parse_status_rss_kb(text: str) -> int | None:
    """Parse VmRSS from /proc/<pid>/status."""

    return _parse_kb_fields(text).get("VmRSS")


def _safe_read_text(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _parse_kb_fields(text: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for raw_line in text.splitlines():
        if ":" not in raw_line:
            continue
        key, raw_value = raw_line.split(":", 1)
        parts = raw_value.strip().split()
        if len(parts) < 2 or parts[1] != "kB":
            continue
        try:
            values[key.strip()] = int(parts[0])
        except ValueError:
            continue
    return values
