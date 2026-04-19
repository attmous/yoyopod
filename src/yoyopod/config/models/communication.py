"""Communication and messaging configuration models."""

from __future__ import annotations

from dataclasses import dataclass

from yoyopod.config.models.core import config_value


@dataclass(slots=True)
class CommunicationAccountConfig:
    """Non-secret SIP identity and transport settings."""

    sip_server: str = config_value(default="sip.linphone.org", env="YOYOPOD_SIP_SERVER")
    sip_username: str = config_value(default="", env="YOYOPOD_SIP_USERNAME")
    sip_identity: str = config_value(default="", env="YOYOPOD_SIP_IDENTITY")
    transport: str = config_value(default="tcp", env="YOYOPOD_SIP_TRANSPORT")
    display_name: str = "YoyoPod"


@dataclass(slots=True)
class CommunicationSecretConfig:
    """Credentials that must stay out of tracked authored config."""

    sip_password: str = config_value(default="", env="YOYOPOD_SIP_PASSWORD")
    sip_password_ha1: str = config_value(default="", env="YOYOPOD_SIP_PASSWORD_HA1")


@dataclass(slots=True)
class CommunicationNetworkConfig:
    """Communication NAT traversal and SIP network settings."""

    stun_server: str = config_value(default="stun.linphone.org", env="YOYOPOD_STUN_SERVER")
    enable_ice: bool = True


@dataclass(slots=True)
class CommunicationAudioConfig:
    """Shared device-truth used by the communication domain."""

    preferred_codec: str = "opus"
    echo_cancellation: bool = True
    mic_gain: int = 80
    playback_device_id: str = config_value(
        default="ALSA: wm8960-soundcard",
        env="YOYOPOD_PLAYBACK_DEVICE",
    )
    ringer_device_id: str = config_value(
        default="ALSA: wm8960-soundcard",
        env="YOYOPOD_RINGER_DEVICE",
    )
    capture_device_id: str = config_value(
        default="ALSA: wm8960-soundcard",
        env="YOYOPOD_CAPTURE_DEVICE",
    )
    media_device_id: str = config_value(
        default="ALSA: wm8960-soundcard",
        env="YOYOPOD_MEDIA_DEVICE",
    )
    ring_output_device: str = config_value(default="", env="YOYOPOD_RING_OUTPUT_DEVICE")


@dataclass(slots=True)
class CommunicationMessagingConfig:
    """Messaging and voice-note policy plus mutable storage paths."""

    conference_factory_uri: str = config_value(
        default="",
        env="YOYOPOD_CONFERENCE_FACTORY_URI",
    )
    file_transfer_server_url: str = config_value(
        default="",
        env="YOYOPOD_FILE_TRANSFER_SERVER_URL",
    )
    lime_server_url: str = config_value(
        default="",
        env="YOYOPOD_LIME_SERVER_URL",
    )
    iterate_interval_ms: int = config_value(
        default=20,
        env="YOYOPOD_VOIP_ITERATE_INTERVAL_MS",
    )
    message_store_dir: str = config_value(
        default="data/communication/messages",
        env="YOYOPOD_MESSAGE_STORE_DIR",
    )
    voice_note_store_dir: str = config_value(
        default="data/communication/voice_notes",
        env="YOYOPOD_VOICE_NOTE_STORE_DIR",
    )
    voice_note_max_duration_seconds: int = config_value(
        default=30,
        env="YOYOPOD_VOICE_NOTE_MAX_DURATION_SECONDS",
    )
    auto_download_incoming_voice_recordings: bool = config_value(
        default=True,
        env="YOYOPOD_AUTO_DOWNLOAD_INCOMING_VOICE_RECORDINGS",
    )


@dataclass(slots=True)
class CommunicationIntegrationsConfig:
    """Config for repo-owned communication integrations."""

    liblinphone_factory_config_path: str = config_value(
        default="config/communication/integrations/liblinphone_factory.conf",
        env="YOYOPOD_LIBLINPHONE_FACTORY_CONFIG",
    )


@dataclass(slots=True)
class CommunicationCallingConfig:
    """Calling-specific policy and runtime state paths."""

    priority_over_music: bool = config_value(default=True, env="YOYOPOD_PRIORITY_OVER_MUSIC")
    auto_answer: bool = False
    ring_duration_seconds: int = config_value(default=30, env="YOYOPOD_RING_DURATION_SECONDS")
    call_timeout: int = 60
    call_history_file: str = config_value(
        default="data/communication/call_history.json",
        env="YOYOPOD_CALL_HISTORY_FILE",
    )
    account: CommunicationAccountConfig = config_value(default_factory=CommunicationAccountConfig)
    network: CommunicationNetworkConfig = config_value(default_factory=CommunicationNetworkConfig)


@dataclass(slots=True)
class CommunicationConfig:
    """Composed communication config built from calling/messaging/device/secret layers."""

    calling: CommunicationCallingConfig = config_value(
        default_factory=CommunicationCallingConfig
    )
    messaging: CommunicationMessagingConfig = config_value(
        default_factory=CommunicationMessagingConfig
    )
    audio: CommunicationAudioConfig = config_value(default_factory=CommunicationAudioConfig)
    integrations: CommunicationIntegrationsConfig = config_value(
        default_factory=CommunicationIntegrationsConfig
    )
    secrets: CommunicationSecretConfig = config_value(default_factory=CommunicationSecretConfig)
