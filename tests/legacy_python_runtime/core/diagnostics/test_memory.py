from __future__ import annotations

from pathlib import Path
from typing import Any

from yoyopod.core.diagnostics.memory import (
    ProcessMemorySnapshot,
    collect_process_memory,
    parse_smaps_rollup,
    parse_status_rss_kb,
)


def test_parse_smaps_rollup_extracts_pss_rss_and_private_dirty() -> None:
    text = """
Rss:               42184 kB
Pss:               19928 kB
Private_Dirty:      7120 kB
SwapPss:              0 kB
""".strip()

    snapshot = parse_smaps_rollup(text, pid=123)

    assert snapshot == ProcessMemorySnapshot(
        pid=123,
        rss_kb=42184,
        pss_kb=19928,
        private_dirty_kb=7120,
        source="smaps_rollup",
    )


def test_parse_status_rss_kb_extracts_vmrss() -> None:
    text = """
Name:\tpython
VmRSS:\t   35100 kB
Threads:\t4
""".strip()

    assert parse_status_rss_kb(text) == 35100


def test_collect_process_memory_uses_status_when_smaps_missing(tmp_path: Path) -> None:
    proc_dir = tmp_path / "123"
    proc_dir.mkdir(parents=True)
    (proc_dir / "status").write_text("VmRSS:\t2048 kB\n", encoding="utf-8")

    snapshot = collect_process_memory(pid=123, proc_root=tmp_path)

    assert snapshot.pid == 123
    assert snapshot.rss_kb == 2048
    assert snapshot.pss_kb is None
    assert snapshot.source == "status"


def test_collect_process_memory_uses_status_when_smaps_read_fails(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    proc_dir = tmp_path / "123"
    proc_dir.mkdir(parents=True)
    smaps_path = proc_dir / "smaps_rollup"
    smaps_path.write_text("Rss: 9999 kB\n", encoding="utf-8")
    status_path = proc_dir / "status"
    status_path.write_text("VmRSS:\t2048 kB\n", encoding="utf-8")
    original_read_text = Path.read_text

    def read_text(path: Path, *args: Any, **kwargs: Any) -> str:
        if path == smaps_path:
            raise PermissionError("smaps unavailable")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)

    snapshot = collect_process_memory(pid=123, proc_root=tmp_path)

    assert snapshot.pid == 123
    assert snapshot.rss_kb == 2048
    assert snapshot.pss_kb is None
    assert snapshot.source == "status"


def test_collect_process_memory_returns_unavailable_when_proc_reads_fail(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    proc_dir = tmp_path / "123"
    proc_dir.mkdir(parents=True)
    (proc_dir / "smaps_rollup").write_text("Rss: 9999 kB\n", encoding="utf-8")
    (proc_dir / "status").write_text("VmRSS:\t2048 kB\n", encoding="utf-8")

    def read_text(_path: Path, *args: Any, **kwargs: Any) -> str:
        raise FileNotFoundError("procfs race")

    monkeypatch.setattr(Path, "read_text", read_text)

    snapshot = collect_process_memory(pid=123, proc_root=tmp_path)

    assert snapshot.pid == 123
    assert snapshot.rss_kb is None
    assert snapshot.pss_kb is None
    assert snapshot.source == "unavailable"


def test_collect_process_memory_returns_unavailable_when_proc_missing(
    tmp_path: Path,
) -> None:
    snapshot = collect_process_memory(pid=999, proc_root=tmp_path)

    assert snapshot.pid == 999
    assert snapshot.rss_kb is None
    assert snapshot.pss_kb is None
    assert snapshot.source == "unavailable"
