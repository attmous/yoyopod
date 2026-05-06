from __future__ import annotations

from types import SimpleNamespace

from yoyopod.core.loop import RuntimeLoopService


class _RustUiHost:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def send_snapshot(self) -> bool:
        self.calls.append(("snapshot", None))
        return True

    def send_tick(self, *, renderer: str = "auto") -> bool:
        self.calls.append(("tick", renderer))
        return True


def test_tick_rust_ui_host_sends_snapshot_then_auto_tick() -> None:
    rust_ui_host = _RustUiHost()
    app = SimpleNamespace(
        _voip_iterate_interval_seconds=0.02,
        rust_ui_host=rust_ui_host,
    )
    loop = RuntimeLoopService(app)

    loop.tick_rust_ui_host()

    assert rust_ui_host.calls == [("snapshot", None), ("tick", "auto")]


def test_tick_rust_ui_host_noops_when_absent() -> None:
    app = SimpleNamespace(
        _voip_iterate_interval_seconds=0.02,
        rust_ui_host=None,
    )
    loop = RuntimeLoopService(app)

    loop.tick_rust_ui_host()
