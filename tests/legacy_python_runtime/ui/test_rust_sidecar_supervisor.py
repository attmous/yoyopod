from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import Mock

from yoyopod.ui.rust_sidecar.protocol import UiEnvelope
from yoyopod.ui.rust_sidecar.supervisor import RustUiSidecarSupervisor


class _FakeProcess:
    def __init__(self) -> None:
        self.stdin = StringIO()
        self.stdout = StringIO(
            UiEnvelope(
                kind="event",
                type="ui.ready",
                payload={"display": {"width": 240}},
            ).to_json_line()
        )
        self.stderr = StringIO()
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.returncode = 0
        return 0

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def test_supervisor_starts_and_sends_shutdown(monkeypatch) -> None:
    fake = _FakeProcess()
    popen = Mock(return_value=fake)
    monkeypatch.setattr("yoyopod.ui.rust_sidecar.supervisor.subprocess.Popen", popen)

    supervisor = RustUiSidecarSupervisor(argv=[str(Path("worker"))])
    ready = supervisor.start()
    supervisor.send(UiEnvelope.command("ui.shutdown"))
    supervisor.stop()

    assert ready.type == "ui.ready"
    assert '"type":"ui.shutdown"' in fake.stdin.getvalue()
    assert fake.terminated
    popen.assert_called_once()
