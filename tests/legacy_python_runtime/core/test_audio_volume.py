from __future__ import annotations

import subprocess

from yoyopod.backends.music import MockMusicBackend
from yoyopod.core import AppContext
from yoyopod.core.audio_volume import AudioVolumeController, OutputVolumeController


class FakeOutputVolume:
    def __init__(self, volume: int | None = None) -> None:
        self.volume = volume
        self.set_calls: list[int] = []

    def set_volume(self, volume: int) -> bool:
        self.volume = volume
        self.set_calls.append(volume)
        return True

    def get_volume(self) -> int | None:
        return self.volume

    def peek_cached_volume(self) -> int | None:
        return self.volume

    def attach_music_backend(self, _backend) -> None:
        return None


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

    monkeypatch.setattr("yoyopod.core.audio_volume.subprocess.run", fake_run)

    controller = OutputVolumeController()

    assert controller.get_system_volume() == 77
    assert controller.get_volume() == 77


def test_output_volume_controller_sets_system_and_music_volume(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("yoyopod.core.audio_volume.subprocess.run", fake_run)

    backend = MockMusicBackend()
    backend.start()
    controller = OutputVolumeController(music_backend=backend)

    assert controller.set_volume(55) is True
    assert calls[:4] == [
        ["aplay", "-l"],
        ["amixer", "-c", "1", "sset", "Playback", "100%"],
        ["amixer", "-c", "1", "sset", "Speaker", "100%"],
        ["amixer", "-c", "1", "sset", "Headphone", "100%"],
    ]
    assert backend.get_volume() == 55


def test_output_volume_controller_pins_detected_wm8960_card_zero(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args == ["aplay", "-l"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=(
                    "card 0: wm8960soundcard [wm8960-soundcard], device 0: "
                    "bcm2835-i2s-wm8960-hifi wm8960-hifi-0 []\n"
                    "card 1: vc4hdmi [vc4-hdmi], device 0: MAI PCM i2s-hifi-0 []\n"
                ),
                stderr="",
            )
        if len(args) >= 5 and args[1:4] == ["-c", "0", "sset"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="missing")

    monkeypatch.setattr("yoyopod.core.audio_volume.subprocess.run", fake_run)

    controller = OutputVolumeController()

    assert controller.set_system_volume(100) is True
    assert calls[:4] == [
        ["aplay", "-l"],
        ["amixer", "-c", "0", "sset", "Playback", "100%"],
        ["amixer", "-c", "0", "sset", "Speaker", "100%"],
        ["amixer", "-c", "0", "sset", "Headphone", "100%"],
    ]


def test_output_volume_controller_falls_back_to_music_backend_when_amixer_missing(
    monkeypatch,
) -> None:
    def fake_run(_args: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("amixer")

    monkeypatch.setattr("yoyopod.core.audio_volume.subprocess.run", fake_run)

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

    monkeypatch.setattr("yoyopod.core.audio_volume.subprocess.run", fake_run)

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

    monkeypatch.setattr("yoyopod.core.audio_volume.subprocess.run", fake_run)
    monkeypatch.setattr(
        "yoyopod.core.audio_volume.logger.warning",
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

    monkeypatch.setattr("yoyopod.core.audio_volume.subprocess.run", fake_run)

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

    monkeypatch.setattr("yoyopod.core.audio_volume.subprocess.run", fake_run)
    monkeypatch.setattr(
        "yoyopod.core.audio_volume.logger.warning",
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


def test_audio_volume_controller_maps_logical_levels_to_configured_max() -> None:
    context = AppContext()
    context.settings["max_volume"] = 55
    output = FakeOutputVolume(50)
    controller = AudioVolumeController(
        context=context,
        default_music_volume_provider=lambda: 55,
        output_volume=output,
    )

    assert controller.get_output_volume_level() == 9

    assert controller.set_output_volume_level(10) == 55
    assert output.set_calls[-1] == 55
    assert context.voice.output_volume == 55
    assert controller.get_output_volume_level() == 10

    assert controller.set_output_volume_level(0) == 0
    assert output.set_calls[-1] == 0
    assert context.voice.output_volume == 0


def test_audio_volume_controller_steps_one_logical_level() -> None:
    context = AppContext()
    context.settings["max_volume"] = 55
    output = FakeOutputVolume(50)
    controller = AudioVolumeController(
        context=context,
        default_music_volume_provider=lambda: 55,
        output_volume=output,
    )

    assert controller.volume_level_up() == 55
    assert output.set_calls[-1] == 55
    assert context.voice.output_volume == 55

    assert controller.volume_level_down() == 50
    assert output.set_calls[-1] == 50
    assert context.voice.output_volume == 50
