from __future__ import annotations

import subprocess

from yoyopy.audio.music.backend import MockMusicBackend
from yoyopy.audio.volume import OutputVolumeController


def test_output_volume_controller_parses_system_volume(monkeypatch) -> None:
    def fake_run(args: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="""
Simple mixer control 'Master',0
  Front Left: Playback 50462 [77%] [on]
  Front Right: Playback 50462 [77%] [on]
""",
            stderr="",
        )

    monkeypatch.setattr("yoyopy.audio.volume.subprocess.run", fake_run)

    controller = OutputVolumeController()

    assert controller.get_system_volume() == 77
    assert controller.get_volume() == 77


def test_output_volume_controller_sets_system_and_music_volume(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("yoyopy.audio.volume.subprocess.run", fake_run)

    backend = MockMusicBackend()
    backend.start()
    controller = OutputVolumeController(music_backend=backend)

    assert controller.set_volume(55) is True
    assert calls == [["amixer", "sset", "Master", "55%"]]
    assert backend.get_volume() == 55


def test_output_volume_controller_falls_back_to_music_backend_when_amixer_missing(
    monkeypatch,
) -> None:
    def fake_run(_args: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("amixer")

    monkeypatch.setattr("yoyopy.audio.volume.subprocess.run", fake_run)

    backend = MockMusicBackend()
    backend.start()
    controller = OutputVolumeController(music_backend=backend)

    assert controller.set_volume(68) is True
    assert controller.get_volume() == 68
    assert backend.get_volume() == 68
