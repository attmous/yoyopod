"""Focused tests for the pygame-backed music manager."""

from __future__ import annotations

from yoyopod.audio.manager import MusicManager


def test_music_manager_skips_pygame_import_when_simulating(monkeypatch) -> None:
    """Simulation mode should not import pygame.mixer at all."""

    import_calls: list[str] = []

    monkeypatch.setattr(
        "yoyopod.audio.manager._load_pygame_mixer",
        lambda: import_calls.append("pygame.mixer"),
    )

    manager = MusicManager(simulate=True)

    assert manager.simulate is True
    assert import_calls == []


def test_music_manager_imports_and_initializes_pygame_on_demand(monkeypatch) -> None:
    """Real audio mode should import and initialize pygame.mixer lazily."""

    init_calls: list[tuple[int, int, int, int]] = []

    class FakeMusic:
        def stop(self) -> None:
            return None

    class FakeMixer:
        music = FakeMusic()

        def init(self, *, frequency: int, size: int, channels: int, buffer: int) -> None:
            init_calls.append((frequency, size, channels, buffer))

        def quit(self) -> None:
            return None

    monkeypatch.setattr("yoyopod.audio.manager._load_pygame_mixer", lambda: FakeMixer())
    monkeypatch.setattr(MusicManager, "_detect_devices", lambda self: [])

    manager = MusicManager(simulate=False)

    assert manager.simulate is False
    assert init_calls == [
        (
            MusicManager.SAMPLE_RATE,
            -16,
            MusicManager.CHANNELS,
            MusicManager.BUFFER_SIZE,
        )
    ]
