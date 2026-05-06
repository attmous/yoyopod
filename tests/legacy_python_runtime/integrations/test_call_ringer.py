"""Focused tests for the canonical call ring-tone helper."""

from __future__ import annotations

from yoyopod.integrations.call import CallRinger


class _ConfigManagerStub:
    def get_ring_output_device(self) -> str:
        return "wm8960-soundcard"

    def get_speaker_test_path(self) -> str:
        return "/usr/bin/speaker-test"


class _PopenStub:
    def __init__(self, *_args, **_kwargs) -> None:
        self.terminated = False
        self.wait_timeout: float | None = None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float) -> None:
        self.wait_timeout = timeout


def test_call_ringer_builds_canonical_command() -> None:
    """Ring tone command should use the configured speaker-test path and device."""

    command = CallRinger.build_command(_ConfigManagerStub())

    assert command == [
        "/usr/bin/speaker-test",
        "-t",
        "sine",
        "-f",
        "800",
        "-D",
        "wm8960-soundcard",
    ]


def test_call_ringer_start_and_stop_manage_process(monkeypatch) -> None:
    """CallRinger should manage the speaker-test subprocess lifecycle."""

    process = _PopenStub()
    popen_calls: list[list[str]] = []

    def _fake_popen(command, **_kwargs):
        popen_calls.append(list(command))
        return process

    monkeypatch.setattr("yoyopod.integrations.call.ringer.subprocess.Popen", _fake_popen)

    ringer = CallRinger()
    ringer.start(_ConfigManagerStub())
    ringer.stop()

    assert popen_calls == [CallRinger.build_command(_ConfigManagerStub())]
    assert process.terminated is True
    assert process.wait_timeout == 1.0
