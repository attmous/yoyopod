from __future__ import annotations

import subprocess

from yoyopod.audio.music.backend import MockMusicBackend
from yoyopod.audio.volume import OutputVolumeController


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

    monkeypatch.setattr("yoyopod.audio.volume.subprocess.run", fake_run)

    controller = OutputVolumeController()

    assert controller.get_system_volume() == 77
    assert controller.get_volume() == 77


def test_output_volume_controller_sets_system_and_music_volume(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("yoyopod.audio.volume.subprocess.run", fake_run)

    backend = MockMusicBackend()
    backend.start()
    controller = OutputVolumeController(music_backend=backend)

    assert controller.set_volume(55) is True
    assert calls[:3] == [
        ["amixer", "-c", "1", "sset", "Playback", "100%"],
        ["amixer", "-c", "1", "sset", "Speaker", "100%"],
        ["amixer", "-c", "1", "sset", "Headphone", "100%"],
    ]
    assert backend.get_volume() == 55


def test_output_volume_controller_falls_back_to_music_backend_when_amixer_missing(
    monkeypatch,
) -> None:
    def fake_run(_args: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("amixer")

    monkeypatch.setattr("yoyopod.audio.volume.subprocess.run", fake_run)

    backend = MockMusicBackend()
    backend.start()
    controller = OutputVolumeController(music_backend=backend)

    assert controller.set_volume(68) is True
    assert controller.get_volume() == 68
    assert backend.get_volume() == 68


def test_output_volume_controller_falls_back_to_card_one_when_default_card_fails(
    monkeypatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args in (
            ["amixer", "sget", "Master"],
            ["amixer", "-c", "1", "sget", "Master"],
            ["amixer", "-c", "0", "sget", "Master"],
            ["amixer", "sget", "Playback"],
            ["amixer", "-c", "1", "sget", "Playback"],
            ["amixer", "-c", "0", "sget", "Playback"],
        ):
            return subprocess.CompletedProcess(
                args=args,
                returncode=1,
                stdout="",
                stderr="amixer: Unable to find simple control 'Master',0",
            )
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="""
Simple mixer control 'Master',0
  Front Left: Playback 65536 [100%] [on]
""",
            stderr="",
        )

    monkeypatch.setattr("yoyopod.audio.volume.subprocess.run", fake_run)

    controller = OutputVolumeController()

    assert controller.get_system_volume() == 100
    assert calls[:7] == [
        ["amixer", "sget", "Master"],
        ["amixer", "-c", "1", "sget", "Master"],
        ["amixer", "-c", "0", "sget", "Master"],
        ["amixer", "sget", "Playback"],
        ["amixer", "-c", "1", "sget", "Playback"],
        ["amixer", "-c", "0", "sget", "Playback"],
        ["amixer", "-c", "1", "sget", "Headset"],
    ]


def test_output_volume_controller_warns_only_once_when_system_control_missing(
    monkeypatch,
) -> None:
    warnings: list[str] = []

    def fake_run(args: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr="amixer: Unable to find simple control",
        )

    monkeypatch.setattr("yoyopod.audio.volume.subprocess.run", fake_run)
    monkeypatch.setattr(
        "yoyopod.audio.volume.logger.warning",
        lambda message, *args: warnings.append(message.format(*args)),
    )

    controller = OutputVolumeController()

    assert controller.get_system_volume() is None
    assert controller.get_system_volume() is None
    assert warnings == ["Could not read ALSA output volume for Master"]


def test_output_volume_controller_prefers_headset_when_present(
    monkeypatch,
) -> None:
    def fake_run(args: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        if args == ["amixer", "-c", "1", "sget", "Headset"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="""
Simple mixer control 'Headset',0
  Front Left: Playback 58982 [90%] [on]
""",
                stderr="",
            )
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="")

    monkeypatch.setattr("yoyopod.audio.volume.subprocess.run", fake_run)

    controller = OutputVolumeController()

    assert controller.get_system_volume() == 90


def test_output_volume_controller_marks_system_available_again_after_success(
    monkeypatch,
) -> None:
    warnings: list[str] = []
    headset_reads = 0

    def fake_run(args: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        nonlocal headset_reads
        if args == ["amixer", "-c", "1", "sget", "Headset"]:
            headset_reads += 1
            if headset_reads == 1:
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="missing")
            if headset_reads == 2:
                return subprocess.CompletedProcess(
                    args=args,
                    returncode=0,
                    stdout="""
Simple mixer control 'Headset',0
  Front Left: Playback 32768 [50%] [on]
""",
                    stderr="",
                )
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="missing")
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="missing")

    monkeypatch.setattr("yoyopod.audio.volume.subprocess.run", fake_run)
    monkeypatch.setattr(
        "yoyopod.audio.volume.logger.warning",
        lambda message, *args: warnings.append(message.format(*args)),
    )

    controller = OutputVolumeController()

    assert controller.get_system_volume() is None
    assert controller.get_system_volume() == 50
    assert controller.get_system_volume() is None
    assert warnings == [
        "Could not read ALSA output volume for Master",
        "Could not read ALSA output volume for Master",
    ]
