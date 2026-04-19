#!/usr/bin/env python3
"""Tests for typed YAML-plus-env configuration models."""

from __future__ import annotations

from pathlib import Path

import yaml

from yoyopod.config import (
    ConfigManager,
    MediaConfig,
    PowerConfig,
    VoiceConfig,
    YoyoPodConfig,
    load_config_model_from_yaml,
)


def test_app_shell_defaults_do_not_require_a_file(tmp_path, monkeypatch) -> None:
    """Missing app-shell config should resolve to typed defaults in memory."""

    monkeypatch.delenv("YOYOPOD_MUSIC_DIR", raising=False)
    monkeypatch.delenv("YOYOPOD_MPV_SOCKET", raising=False)
    monkeypatch.delenv("YOYOPOD_MPV_BINARY", raising=False)
    monkeypatch.delenv("YOYOPOD_ALSA_DEVICE", raising=False)
    monkeypatch.delenv("YOYOPOD_AUTO_RESUME_AFTER_CALL", raising=False)
    monkeypatch.delenv("YOYOPOD_DISPLAY", raising=False)
    monkeypatch.delenv("YOYOPOD_VOICE_COMMANDS_ENABLED", raising=False)
    monkeypatch.delenv("YOYOPOD_VOSK_MODEL_PATH", raising=False)

    config_file = tmp_path / "app" / "core.yaml"
    settings = load_config_model_from_yaml(YoyoPodConfig, config_file)

    assert not config_file.exists()
    assert settings.input.ptt_navigation is True
    assert settings.input.whisplay_double_tap_ms == 300
    assert settings.input.whisplay_long_hold_ms == 800
    assert not hasattr(settings, "power")
    assert settings.display.hardware == "auto"
    assert settings.display.whisplay_renderer == "lvgl"
    assert settings.display.lvgl_buffer_lines == 40
    assert settings.logging.file == "logs/yoyopod.log"
    assert settings.logging.error_file == "logs/yoyopod_errors.log"
    assert settings.logging.pid_file == "/tmp/yoyopod.pid"
    assert settings.logging.rotation == "5 MB"
    assert settings.logging.retention == "3 days"
    assert settings.logging.error_rotation == "2 MB"
    assert settings.logging.error_retention == "7 days"
    assert settings.logging.enqueue is False
    assert settings.logging.backtrace is True
    assert settings.logging.diagnose is True
    assert settings.diagnostics.responsiveness_watchdog_enabled is False
    assert settings.diagnostics.responsiveness_watchdog_poll_interval_seconds == 1.0
    assert settings.diagnostics.responsiveness_stall_threshold_seconds == 5.0
    assert settings.diagnostics.responsiveness_capture_cooldown_seconds == 30.0
    assert settings.diagnostics.responsiveness_recent_input_window_seconds == 3.0
    assert settings.diagnostics.responsiveness_capture_dir == "logs/responsiveness"


def test_power_config_defaults_do_not_require_a_file(tmp_path, monkeypatch) -> None:
    """Missing power config should still resolve to typed PiSugar defaults."""

    monkeypatch.delenv("YOYOPOD_POWER_ENABLED", raising=False)
    monkeypatch.delenv("YOYOPOD_POWER_TRANSPORT", raising=False)
    monkeypatch.delenv("YOYOPOD_PISUGAR_PORT", raising=False)
    monkeypatch.delenv("YOYOPOD_LOW_BATTERY_WARNING_PERCENT", raising=False)
    monkeypatch.delenv("YOYOPOD_CRITICAL_BATTERY_SHUTDOWN_PERCENT", raising=False)
    monkeypatch.delenv("YOYOPOD_POWER_SHUTDOWN_COMMAND", raising=False)
    monkeypatch.delenv("YOYOPOD_POWER_WATCHDOG_ENABLED", raising=False)
    monkeypatch.delenv("YOYOPOD_POWER_WATCHDOG_I2C_ADDRESS", raising=False)

    config_file = tmp_path / "power" / "backend.yaml"
    settings = load_config_model_from_yaml(PowerConfig, config_file)

    assert not config_file.exists()
    assert settings.enabled is True
    assert settings.backend == "pisugar"
    assert settings.transport == "auto"
    assert settings.socket_path == "/tmp/pisugar-server.sock"
    assert settings.tcp_port == 8423
    assert settings.low_battery_warning_percent == 20.0
    assert settings.low_battery_warning_cooldown_seconds == 300.0
    assert settings.auto_shutdown_enabled is True
    assert settings.critical_shutdown_percent == 10.0
    assert settings.shutdown_delay_seconds == 15.0
    assert settings.shutdown_command == "sudo -n shutdown -h now"
    assert settings.shutdown_state_file == "data/last_shutdown_state.json"
    assert settings.watchdog_enabled is False
    assert settings.watchdog_timeout_seconds == 60
    assert settings.watchdog_feed_interval_seconds == 15.0
    assert settings.watchdog_i2c_bus == 1
    assert settings.watchdog_i2c_address == 0x57


def test_media_config_defaults_do_not_require_a_file(tmp_path, monkeypatch) -> None:
    """Missing media config should still resolve to typed defaults."""

    monkeypatch.delenv("YOYOPOD_MUSIC_DIR", raising=False)
    monkeypatch.delenv("YOYOPOD_MPV_SOCKET", raising=False)
    monkeypatch.delenv("YOYOPOD_MPV_BINARY", raising=False)
    monkeypatch.delenv("YOYOPOD_ALSA_DEVICE", raising=False)
    monkeypatch.delenv("YOYOPOD_AUTO_RESUME_AFTER_CALL", raising=False)
    monkeypatch.delenv("YOYOPOD_DEFAULT_VOLUME", raising=False)
    monkeypatch.delenv("YOYOPOD_RECENT_TRACKS_FILE", raising=False)

    config_file = tmp_path / "audio" / "music.yaml"
    settings = load_config_model_from_yaml(MediaConfig, config_file)

    assert not config_file.exists()
    assert settings.music.music_dir == "/home/pi/Music"
    assert settings.music.mpv_socket == ""
    assert settings.music.mpv_binary == "mpv"
    assert settings.audio.alsa_device == "default"
    assert settings.music.default_volume == 100
    assert settings.music.auto_resume_after_call is True
    assert settings.music.speaker_test_path == "speaker-test"
    assert settings.music.recent_tracks_file == "data/media/recent_tracks.json"


def test_voice_config_defaults_do_not_require_a_file(tmp_path, monkeypatch) -> None:
    """Missing voice config should still resolve to typed assistant and device defaults."""

    monkeypatch.delenv("YOYOPOD_VOICE_COMMANDS_ENABLED", raising=False)
    monkeypatch.delenv("YOYOPOD_VOSK_MODEL_PATH", raising=False)
    monkeypatch.delenv("YOYOPOD_VOSK_MODEL_KEEP_LOADED", raising=False)
    monkeypatch.delenv("YOYOPOD_VOICE_SPEAKER_DEVICE", raising=False)

    config_file = tmp_path / "voice" / "assistant.yaml"
    settings = load_config_model_from_yaml(VoiceConfig, config_file)

    assert not config_file.exists()
    assert settings.assistant.commands_enabled is True
    assert settings.assistant.ai_requests_enabled is True
    assert settings.assistant.screen_read_enabled is False
    assert settings.assistant.stt_backend == "vosk"
    assert settings.assistant.tts_backend == "espeak-ng"
    assert settings.assistant.vosk_model_path == "models/vosk-model-small-en-us"
    assert settings.assistant.vosk_model_keep_loaded is True
    assert settings.assistant.sample_rate_hz == 16000
    assert settings.assistant.tts_rate_wpm == 155
    assert settings.audio.speaker_device_id == ""
    assert settings.audio.capture_device_id == ""


def test_config_manager_app_config_merges_yaml_and_env(tmp_path, monkeypatch) -> None:
    """Environment variables should override YAML while preserving other values."""

    app_file = tmp_path / "app" / "core.yaml"
    app_file.parent.mkdir(parents=True, exist_ok=True)
    app_file.write_text(
        yaml.safe_dump(
            {
                "ui": {
                    "theme": "dark",
                },
                "logging": {
                    "level": "DEBUG",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    device_file = tmp_path / "device" / "hardware.yaml"
    device_file.parent.mkdir(parents=True, exist_ok=True)
    device_file.write_text(
        yaml.safe_dump(
            {
                "display": {
                    "hardware": "pimoroni",
                },
                "media_audio": {
                    "alsa_device": "hw:Loopback,0",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    audio_file = tmp_path / "audio" / "music.yaml"
    audio_file.parent.mkdir(parents=True, exist_ok=True)
    audio_file.write_text(
        yaml.safe_dump(
            {
                "audio": {
                    "music_dir": "/srv/music",
                    "mpv_binary": "/usr/local/bin/mpv",
                    "auto_resume_after_call": True,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    power_file = tmp_path / "power" / "backend.yaml"
    power_file.parent.mkdir(parents=True, exist_ok=True)
    power_file.write_text(
        yaml.safe_dump(
            {
                "power": {
                    "enabled": True,
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("YOYOPOD_MPV_SOCKET", "/tmp/test-mpv.sock")
    monkeypatch.setenv("YOYOPOD_AUTO_RESUME_AFTER_CALL", "false")
    monkeypatch.setenv("YOYOPOD_WHISPLAY_DOUBLE_TAP_MS", "260")
    monkeypatch.setenv("YOYOPOD_WHISPLAY_LONG_HOLD_MS", "900")
    monkeypatch.setenv("YOYOPOD_POWER_TRANSPORT", "tcp")
    monkeypatch.setenv("YOYOPOD_PISUGAR_PORT", "9001")
    monkeypatch.setenv("YOYOPOD_LOW_BATTERY_WARNING_PERCENT", "17.5")
    monkeypatch.setenv("YOYOPOD_CRITICAL_BATTERY_SHUTDOWN_PERCENT", "8.5")
    monkeypatch.setenv("YOYOPOD_POWER_SHUTDOWN_DELAY_SECONDS", "22.0")
    monkeypatch.setenv("YOYOPOD_POWER_SHUTDOWN_COMMAND", "sudo -n poweroff")
    monkeypatch.setenv("YOYOPOD_POWER_WATCHDOG_ENABLED", "true")
    monkeypatch.setenv("YOYOPOD_POWER_WATCHDOG_TIMEOUT_SECONDS", "90")
    monkeypatch.setenv("YOYOPOD_POWER_WATCHDOG_FEED_INTERVAL_SECONDS", "30")
    monkeypatch.setenv("YOYOPOD_POWER_WATCHDOG_I2C_ADDRESS", "0x58")
    monkeypatch.setenv("YOYOPOD_DISPLAY", "whisplay")
    monkeypatch.setenv("YOYOPOD_WHISPLAY_RENDERER", "lvgl")
    monkeypatch.setenv("YOYOPOD_LVGL_BUFFER_LINES", "24")
    monkeypatch.setenv("YOYOPOD_VOICE_COMMANDS_ENABLED", "false")
    monkeypatch.setenv("YOYOPOD_SCREEN_READ_ENABLED", "true")
    monkeypatch.setenv("YOYOPOD_VOSK_MODEL_PATH", "/srv/models/vosk-small")
    monkeypatch.setenv("YOYOPOD_VOSK_MODEL_KEEP_LOADED", "false")
    monkeypatch.setenv("YOYOPOD_LOG_FILE", "/var/log/yoyopod.log")
    monkeypatch.setenv("YOYOPOD_ERROR_LOG_FILE", "/var/log/yoyopod_errors.log")
    monkeypatch.setenv("YOYOPOD_PID_FILE", "/run/yoyopod.pid")
    monkeypatch.setenv("YOYOPOD_LOG_ENQUEUE", "true")
    monkeypatch.setenv("YOYOPOD_RESPONSIVENESS_WATCHDOG_ENABLED", "true")
    monkeypatch.setenv("YOYOPOD_RESPONSIVENESS_STALL_THRESHOLD_SECONDS", "8.0")
    monkeypatch.setenv("YOYOPOD_RESPONSIVENESS_CAPTURE_DIR", "/tmp/yoyopod-watchdog")

    config_manager = ConfigManager(config_dir=str(tmp_path))
    settings = config_manager.get_app_settings()
    media_settings = config_manager.get_media_settings()
    power_settings = config_manager.get_power_settings()
    voice_settings = config_manager.get_voice_settings()
    config_dict = config_manager.get_app_config_dict()
    media_dict = config_manager.get_media_config_dict()
    power_dict = config_manager.get_power_config_dict()
    runtime_dict = config_manager.get_runtime_config_dict()

    assert config_manager.app_config_loaded is True
    assert config_manager.media_config_loaded is True
    assert config_manager.power_config_loaded is True
    assert not hasattr(settings, "audio")
    assert not hasattr(settings, "power")
    assert media_settings.music.music_dir == "/srv/music"
    assert media_settings.music.mpv_socket == "/tmp/test-mpv.sock"
    assert media_settings.music.mpv_binary == "/usr/local/bin/mpv"
    assert media_settings.audio.alsa_device == "hw:Loopback,0"
    assert media_settings.music.auto_resume_after_call is False
    assert settings.input.whisplay_double_tap_ms == 260
    assert settings.input.whisplay_long_hold_ms == 900
    assert power_settings.transport == "tcp"
    assert power_settings.tcp_port == 9001
    assert power_settings.low_battery_warning_percent == 17.5
    assert power_settings.critical_shutdown_percent == 8.5
    assert power_settings.shutdown_delay_seconds == 22.0
    assert power_settings.shutdown_command == "sudo -n poweroff"
    assert power_settings.watchdog_enabled is True
    assert power_settings.watchdog_timeout_seconds == 90
    assert power_settings.watchdog_feed_interval_seconds == 30.0
    assert power_settings.watchdog_i2c_address == 0x58
    assert settings.display.hardware == "whisplay"
    assert settings.display.whisplay_renderer == "lvgl"
    assert settings.display.lvgl_buffer_lines == 24
    assert voice_settings.assistant.commands_enabled is False
    assert voice_settings.assistant.screen_read_enabled is True
    assert voice_settings.assistant.vosk_model_path == "/srv/models/vosk-small"
    assert voice_settings.assistant.vosk_model_keep_loaded is False
    assert settings.logging.level == "DEBUG"
    assert settings.logging.file == "/var/log/yoyopod.log"
    assert settings.logging.error_file == "/var/log/yoyopod_errors.log"
    assert settings.logging.pid_file == "/run/yoyopod.pid"
    assert settings.logging.enqueue is True
    assert settings.diagnostics.responsiveness_watchdog_enabled is True
    assert settings.diagnostics.responsiveness_stall_threshold_seconds == 8.0
    assert settings.diagnostics.responsiveness_capture_dir == "/tmp/yoyopod-watchdog"
    assert "audio" not in config_dict
    assert "power" not in config_dict
    assert config_dict["display"]["hardware"] == "whisplay"
    assert config_dict["display"]["whisplay_renderer"] == "lvgl"
    assert config_dict["display"]["lvgl_buffer_lines"] == 24
    assert media_dict["music"]["music_dir"] == "/srv/music"
    assert media_dict["music"]["mpv_socket"] == "/tmp/test-mpv.sock"
    assert media_dict["audio"]["alsa_device"] == "hw:Loopback,0"
    assert power_dict["transport"] == "tcp"
    assert power_dict["watchdog_i2c_address"] == 0x58
    assert runtime_dict["media"]["music"]["music_dir"] == "/srv/music"
    assert runtime_dict["media"]["audio"]["alsa_device"] == "hw:Loopback,0"
    assert runtime_dict["power"]["transport"] == "tcp"
    assert "network" not in config_dict
    assert "voice" not in config_dict
    assert config_dict["logging"]["file"] == "/var/log/yoyopod.log"
    assert config_dict["diagnostics"]["responsiveness_watchdog_enabled"] is True


def test_config_manager_keeps_typed_communication_audio_settings(tmp_path, monkeypatch) -> None:
    """Communication settings should stay typed while preserving existing getter behavior."""

    monkeypatch.setenv("YOYOPOD_PLAYBACK_DEVICE", "ALSA: default")
    monkeypatch.setenv("YOYOPOD_RING_OUTPUT_DEVICE", "default")
    monkeypatch.setenv("YOYOPOD_DEFAULT_VOLUME", "91")

    config_manager = ConfigManager(config_dir=str(tmp_path))

    assert config_manager.get_communication_settings().audio.playback_device_id == "ALSA: default"
    assert config_manager.get_default_output_volume() == 91
    assert config_manager.get_playback_device_id() == "ALSA: default"
    assert config_manager.get_ring_output_device() == "default"


def test_config_manager_keeps_liblinphone_factory_config_path(tmp_path, monkeypatch) -> None:
    """Communication config should expose the Liblinphone factory config path with env override support."""

    monkeypatch.setenv(
        "YOYOPOD_LIBLINPHONE_FACTORY_CONFIG", "config/custom_liblinphone_factory.conf"
    )

    config_manager = ConfigManager(config_dir=str(tmp_path))

    assert (
        config_manager.get_communication_settings().integrations.liblinphone_factory_config_path
        == "config/custom_liblinphone_factory.conf"
    )
    assert config_manager.get_voip_factory_config_path() == "config/custom_liblinphone_factory.conf"


def test_config_manager_exposes_lime_server_url(tmp_path, monkeypatch) -> None:
    """Communication config should expose the configured LIME/X3DH server URL."""

    monkeypatch.setenv(
        "YOYOPOD_LIME_SERVER_URL", "https://lime.example.com/lime-server/lime-server.php"
    )

    config_manager = ConfigManager(config_dir=str(tmp_path))

    assert (
        config_manager.get_communication_settings().messaging.lime_server_url
        == "https://lime.example.com/lime-server/lime-server.php"
    )
    assert (
        config_manager.get_lime_server_url()
        == "https://lime.example.com/lime-server/lime-server.php"
    )


def test_config_manager_exposes_conference_factory_uri(tmp_path, monkeypatch) -> None:
    """Communication config should expose the configured conference-factory URI."""

    monkeypatch.setenv("YOYOPOD_CONFERENCE_FACTORY_URI", "sip:conference-factory@example.com")

    config_manager = ConfigManager(config_dir=str(tmp_path))

    assert (
        config_manager.get_communication_settings().messaging.conference_factory_uri
        == "sip:conference-factory@example.com"
    )
    assert config_manager.get_conference_factory_uri() == "sip:conference-factory@example.com"


def test_gpio_pin_config_from_yaml_dict():
    """GpioPin and PimoroniGpioConfig should load from nested YAML dicts."""
    from yoyopod.config.models import (
        AppDisplayConfig,
        GpioPin,
        PimoroniGpioConfig,
        build_config_model,
    )

    data = {
        "pimoroni_gpio": {
            "spi_bus": 1,
            "spi_device": 0,
            "spi_speed_hz": 60000000,
            "dc": {"chip": "gpiochip0", "line": 109},
            "cs": {"chip": "gpiochip0", "line": 110},
            "backlight": {"chip": "gpiochip1", "line": 35},
            "led_r": {"chip": "gpiochip0", "line": 33},
            "led_g": {"chip": "gpiochip1", "line": 6},
            "led_b": {"chip": "gpiochip1", "line": 7},
        }
    }
    config = build_config_model(AppDisplayConfig, data)
    assert config.pimoroni_gpio is not None
    assert config.pimoroni_gpio.spi_bus == 1
    assert config.pimoroni_gpio.dc == GpioPin(chip="gpiochip0", line=109)
    assert config.pimoroni_gpio.cs == GpioPin(chip="gpiochip0", line=110)
    assert config.pimoroni_gpio.backlight == GpioPin(chip="gpiochip1", line=35)
    assert config.pimoroni_gpio.led_r == GpioPin(chip="gpiochip0", line=33)


def test_gpio_input_config_from_yaml_dict():
    """PimoroniGpioInputConfig should load from nested YAML dicts."""
    from yoyopod.config.models import (
        AppInputConfig,
        GpioPin,
        PimoroniGpioInputConfig,
        build_config_model,
    )

    data = {
        "pimoroni_gpio": {
            "button_a": {"chip": "gpiochip0", "line": 34},
            "button_b": {"chip": "gpiochip0", "line": 35},
            "button_x": {"chip": "gpiochip0", "line": 36},
            "button_y": {"chip": "gpiochip0", "line": 313},
        }
    }
    config = build_config_model(AppInputConfig, data)
    assert config.pimoroni_gpio is not None
    assert config.pimoroni_gpio.button_a == GpioPin(chip="gpiochip0", line=34)
    assert config.pimoroni_gpio.button_y == GpioPin(chip="gpiochip0", line=313)


def test_display_config_defaults_pimoroni_gpio_to_none():
    """When no pimoroni_gpio section exists, it should default to None."""
    from yoyopod.config.models import AppDisplayConfig, build_config_model

    config = build_config_model(AppDisplayConfig, {})
    assert config.pimoroni_gpio is None


def test_top_level_config_exports_config_value() -> None:
    """Top-level config package should mirror the field helper export."""

    from yoyopod.config import config_value
    from yoyopod.config.models import config_value as models_config_value

    assert config_value is models_config_value
