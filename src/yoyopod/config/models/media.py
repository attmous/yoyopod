"""Media configuration models."""

from __future__ import annotations

from dataclasses import dataclass

from yoyopod.config.models.core import config_value


@dataclass(slots=True)
class MediaMusicConfig:
    """Local music playback policy and runtime paths."""

    music_dir: str = config_value(default="/home/pi/Music", env="YOYOPOD_MUSIC_DIR")
    mpv_socket: str = config_value(default="", env="YOYOPOD_MPV_SOCKET")
    mpv_binary: str = config_value(default="mpv", env="YOYOPOD_MPV_BINARY")
    auto_resume_after_call: bool = config_value(
        default=True,
        env="YOYOPOD_AUTO_RESUME_AFTER_CALL",
    )
    fade_out_duration_ms: int = config_value(default=0, env="YOYOPOD_FADE_OUT_DURATION_MS")
    fade_in_duration_ms: int = config_value(default=0, env="YOYOPOD_FADE_IN_DURATION_MS")
    default_volume: int = config_value(default=100, env="YOYOPOD_DEFAULT_VOLUME")
    speaker_test_path: str = config_value(default="speaker-test", env="YOYOPOD_SPEAKER_TEST_PATH")
    recent_tracks_file: str = config_value(
        default="data/media/recent_tracks.json",
        env="YOYOPOD_RECENT_TRACKS_FILE",
    )


@dataclass(slots=True)
class MediaAudioConfig:
    """Device-owned playback routing for the local media domain."""

    alsa_device: str = config_value(default="default", env="YOYOPOD_ALSA_DEVICE")


@dataclass(slots=True)
class MediaConfig:
    """Composed media/audio config built from music policy and device-owned routing."""

    music: MediaMusicConfig = config_value(default_factory=MediaMusicConfig)
    audio: MediaAudioConfig = config_value(default_factory=MediaAudioConfig)
