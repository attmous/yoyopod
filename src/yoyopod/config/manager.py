"""Canonical config composition for YoyoPod."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from yoyopod.config.composition import (
    DEVICE_HARDWARE_CONFIG,
    APP_CORE_CONFIG,
    config_loaded,
    merge_layer_groups,
)
from yoyopod.config.layers import resolve_config_board, resolve_config_layers
from yoyopod.config.models import (
    CloudConfig,
    CloudSecretsConfig,
    CommunicationConfig,
    MediaConfig,
    NetworkConfig,
    PeopleDirectoryConfig,
    PowerConfig,
    VoiceConfig,
    YoyoPodConfig,
    YoyoPodRuntimeConfig,
    build_config_model,
    config_to_dict,
)
from yoyopod.config.storage import (
    atomic_write_yaml,
    deep_merge_mappings,
    load_yaml_layers,
    load_yaml_mapping,
)

AUDIO_MUSIC_CONFIG = Path("audio/music.yaml")
POWER_BACKEND_CONFIG = Path("power/backend.yaml")
NETWORK_CELLULAR_CONFIG = Path("network/cellular.yaml")
VOICE_ASSISTANT_CONFIG = Path("voice/assistant.yaml")
COMMUNICATION_CALLING_CONFIG = Path("communication/calling.yaml")
COMMUNICATION_MESSAGING_CONFIG = Path("communication/messaging.yaml")
COMMUNICATION_SECRETS_CONFIG = Path("communication/calling.secrets.yaml")
PEOPLE_DIRECTORY_CONFIG = Path("people/directory.yaml")
CLOUD_BACKEND_CONFIG = Path("cloud/backend.yaml")
CLOUD_SECRETS_CONFIG = Path("cloud/device.secrets.yaml")
SYSTEM_CLOUD_SECRETS_FILE = Path("/etc/yoyopod/cloud/device.secrets.yaml")
_SECRET_KEYS = ("sip_password", "sip_password_ha1")


class ConfigManager:
    """Compose authored config files into one typed runtime model."""

    def __init__(
        self,
        config_dir: str = "config",
        config_board: str | None = None,
    ) -> None:
        self.config_dir = Path(config_dir)
        self.config_board = resolve_config_board(explicit_board=config_board)

        self.app_core_layers = resolve_config_layers(
            self.config_dir,
            self.config_board,
            APP_CORE_CONFIG,
        )
        self.media_music_layers = resolve_config_layers(
            self.config_dir,
            self.config_board,
            AUDIO_MUSIC_CONFIG,
        )
        self.device_hardware_layers = resolve_config_layers(
            self.config_dir,
            self.config_board,
            DEVICE_HARDWARE_CONFIG,
        )
        self.power_backend_layers = resolve_config_layers(
            self.config_dir,
            self.config_board,
            POWER_BACKEND_CONFIG,
        )
        self.network_cellular_layers = resolve_config_layers(
            self.config_dir,
            self.config_board,
            NETWORK_CELLULAR_CONFIG,
        )
        self.voice_assistant_layers = resolve_config_layers(
            self.config_dir,
            self.config_board,
            VOICE_ASSISTANT_CONFIG,
        )
        self.communication_calling_layers = resolve_config_layers(
            self.config_dir,
            self.config_board,
            COMMUNICATION_CALLING_CONFIG,
        )
        self.communication_messaging_layers = resolve_config_layers(
            self.config_dir,
            self.config_board,
            COMMUNICATION_MESSAGING_CONFIG,
        )
        self.people_directory_layers = resolve_config_layers(
            self.config_dir,
            self.config_board,
            PEOPLE_DIRECTORY_CONFIG,
        )
        self.cloud_backend_layers = resolve_config_layers(
            self.config_dir,
            self.config_board,
            CLOUD_BACKEND_CONFIG,
        )
        self.communication_secrets_file = self.config_dir / COMMUNICATION_SECRETS_CONFIG
        self.cloud_secrets_file = self.config_dir / CLOUD_SECRETS_CONFIG
        self.cloud_secrets_runtime_file = (
            self.cloud_secrets_file
            if self.cloud_secrets_file.exists()
            else SYSTEM_CLOUD_SECRETS_FILE
        )

        self.app_config_file = self.app_core_layers[-1]
        self.device_hardware_file = self.device_hardware_layers[-1]
        self.media_music_file = self.media_music_layers[-1]
        self.power_backend_file = self.power_backend_layers[-1]
        self.network_cellular_file = self.network_cellular_layers[-1]
        self.voice_assistant_file = self.voice_assistant_layers[-1]
        self.communication_calling_file = self.communication_calling_layers[-1]
        self.communication_messaging_file = self.communication_messaging_layers[-1]
        self.people_directory_file = self.people_directory_layers[-1]
        self.cloud_backend_file = self.cloud_backend_layers[-1]

        self.app_settings = YoyoPodConfig()
        self.media_settings = MediaConfig()
        self.power_settings = PowerConfig()
        self.network_settings = NetworkConfig()
        self.voice_settings = VoiceConfig()
        self.communication_settings = CommunicationConfig()
        self.people_settings = PeopleDirectoryConfig()
        self.cloud_settings = CloudConfig()
        self.runtime_settings = YoyoPodRuntimeConfig()

        self.app_config: dict[str, Any] = config_to_dict(self.app_settings)
        self.media_config: dict[str, Any] = config_to_dict(self.media_settings)
        self.power_config: dict[str, Any] = config_to_dict(self.power_settings)
        self.network_config: dict[str, Any] = config_to_dict(self.network_settings)
        self.voice_config: dict[str, Any] = config_to_dict(self.voice_settings)
        self.communication_config: dict[str, Any] = config_to_dict(self.communication_settings)
        self.runtime_config: dict[str, Any] = config_to_dict(self.runtime_settings)

        self.app_config_loaded = False
        self.device_hardware_config_loaded = False
        self.media_config_loaded = False
        self.power_config_loaded = False
        self.network_config_loaded = False
        self.voice_config_loaded = False
        self.communication_config_loaded = False
        self.communication_secrets_loaded = False
        self.people_config_loaded = False
        self.cloud_config_loaded = False
        self.cloud_secrets_loaded = False
        self.cloud_secrets_error = ""
        self._cloud_override_values: dict[str, Any] = {}

        logger.info(
            "ConfigManager initialized (config_dir={}, config_board={})",
            self.config_dir,
            self.config_board or "default",
        )

        self.load_app_config()
        self.load_media_config()
        self.load_power_config()
        self.load_network_config()
        self.load_voice_config()
        self.load_communication_config()
        self.load_people_config()
        self.load_cloud_config()
        self._refresh_runtime_settings()

    def _refresh_runtime_settings(self) -> None:
        """Rebuild the composed runtime model after one domain reloads."""

        self.runtime_settings = YoyoPodRuntimeConfig(
            app=self.app_settings,
            media=self.media_settings,
            power=self.power_settings,
            network=self.network_settings,
            voice=self.voice_settings,
            communication=self.communication_settings,
            people=self.people_settings,
            cloud=self.cloud_settings,
        )
        self.runtime_config = config_to_dict(self.runtime_settings)

    def _save_app_config_layer_patch(self, patch: dict[str, Any]) -> bool:
        """Persist one partial update into the active app layer only."""

        try:
            current = load_yaml_mapping(self.app_config_file)
            data = deep_merge_mappings(current, patch)
            atomic_write_yaml(self.app_config_file, data)
            self.app_config_loaded = True
            logger.info("App configuration layer updated successfully")
            return True
        except Exception:
            logger.exception("Error updating app config layer")
            return False

    def _save_device_hardware_layer_patch(self, patch: dict[str, Any]) -> bool:
        """Persist one partial update into the active device layer only."""

        try:
            current = load_yaml_mapping(self.device_hardware_file)
            data = deep_merge_mappings(current, patch)
            atomic_write_yaml(self.device_hardware_file, data)
            self.device_hardware_config_loaded = True
            logger.info("Device configuration layer updated successfully")
            return True
        except Exception:
            logger.exception("Error updating device config layer")
            return False

    def _app_core_payload(self) -> dict[str, Any]:
        """Return only the sections owned by config/app/core.yaml."""

        return {
            "app": config_to_dict(self.app_settings.app),
            "ui": config_to_dict(self.app_settings.ui),
            "logging": config_to_dict(self.app_settings.logging),
            "diagnostics": config_to_dict(self.app_settings.diagnostics),
        }

    @staticmethod
    def _validate_secret_boundary(payload: dict[str, Any], *, source: str) -> None:
        """Reject secrets that leak into tracked non-secret config files."""

        account = payload.get("calling", {}).get("account", {})
        if isinstance(account, dict):
            leaked = [key for key in _SECRET_KEYS if str(account.get(key, "")).strip()]
            if leaked:
                raise ValueError(
                    f"{source} must not carry secrets ({', '.join(leaked)}); "
                    "use communication/calling.secrets.yaml or env vars"
                )

        secrets = payload.get("secrets", {})
        if isinstance(secrets, dict):
            leaked = [key for key in _SECRET_KEYS if str(secrets.get(key, "")).strip()]
            if leaked:
                raise ValueError(
                    f"{source} must not define a secrets block; "
                    "use communication/calling.secrets.yaml or env vars"
                )

    def load_app_config(self) -> bool:
        """Load the typed app settings from canonical authored files."""

        self.device_hardware_config_loaded = config_loaded(self.device_hardware_layers)
        self.app_config_loaded = config_loaded(
            self.app_core_layers,
            self.device_hardware_layers,
        )
        try:
            payload = merge_layer_groups(
                self.app_core_layers,
                self.device_hardware_layers,
            )
            self.app_settings = build_config_model(YoyoPodConfig, payload)
            self.app_config = config_to_dict(self.app_settings)
            self._refresh_runtime_settings()

            if self.app_config_loaded:
                logger.info(
                    "App configuration loaded from {}",
                    ", ".join(
                        str(path)
                        for group in (
                            self.app_core_layers,
                            self.device_hardware_layers,
                        )
                        for path in group
                        if path.exists()
                    ),
                )
            else:
                logger.warning("No authored app config found; using typed defaults")

            logger.debug("Display hardware: {}", self.app_settings.display.hardware)
            return self.app_config_loaded
        except Exception:
            logger.exception("Error loading app config")
            self.app_settings = YoyoPodConfig()
            self.app_config = config_to_dict(self.app_settings)
            self.app_config_loaded = False
            self._refresh_runtime_settings()
            return False

    def load_media_config(self) -> bool:
        """Load the typed media config from audio-owned and device-owned layers."""

        self.device_hardware_config_loaded = config_loaded(self.device_hardware_layers)
        self.media_config_loaded = config_loaded(
            self.media_music_layers,
            self.device_hardware_layers,
        )
        try:
            music_payload = load_yaml_layers(self.media_music_layers)
            device_payload = load_yaml_layers(self.device_hardware_layers)
            media_policy = music_payload.get("music", music_payload.get("audio", music_payload))
            if not isinstance(media_policy, dict):
                media_policy = {}

            media_audio = device_payload.get("media_audio", {})
            if not isinstance(media_audio, dict):
                media_audio = {}

            payload = {
                "music": media_policy,
                "audio": media_audio,
            }

            self.media_settings = build_config_model(MediaConfig, payload)
            self.media_config = config_to_dict(self.media_settings)
            self._refresh_runtime_settings()

            if self.media_config_loaded:
                logger.info("Media configuration loaded successfully")
            else:
                logger.warning("No authored media config found; using typed defaults")

            logger.debug("Music directory: {}", self.media_settings.music.music_dir)
            logger.debug("Media ALSA device: {}", self.media_settings.audio.alsa_device)
            return self.media_config_loaded
        except Exception:
            logger.exception("Error loading media config")
            self.media_settings = MediaConfig()
            self.media_config = config_to_dict(self.media_settings)
            self.media_config_loaded = False
            self._refresh_runtime_settings()
            return False

    def load_power_config(self) -> bool:
        """Load the typed power config from domain-owned backend layers."""

        self.power_config_loaded = config_loaded(self.power_backend_layers)
        try:
            payload = load_yaml_layers(self.power_backend_layers)
            self.power_settings = build_config_model(PowerConfig, payload.get("power", payload))
            self.power_config = config_to_dict(self.power_settings)
            self._refresh_runtime_settings()

            if self.power_config_loaded:
                logger.info("Power configuration loaded successfully")
            else:
                logger.warning("No authored power config found; using typed defaults")

            return self.power_config_loaded
        except Exception:
            logger.exception("Error loading power config")
            self.power_settings = PowerConfig()
            self.power_config = config_to_dict(self.power_settings)
            self.power_config_loaded = False
            self._refresh_runtime_settings()
            return False

    def save_app_config(self) -> bool:
        """Persist the current app-core layer without collapsing other owned files."""

        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            data = self._app_core_payload()
            atomic_write_yaml(self.app_config_file, data)
            self.app_config = config_to_dict(self.app_settings)
            self.app_config_loaded = True
            self._refresh_runtime_settings()
            logger.info("App configuration saved successfully")
            return True
        except Exception:
            logger.exception("Error saving app config")
            return False

    def load_voice_config(self) -> bool:
        """Load the typed voice config from voice-owned and device-owned layers."""

        self.device_hardware_config_loaded = config_loaded(self.device_hardware_layers)
        self.voice_config_loaded = config_loaded(
            self.voice_assistant_layers,
            self.device_hardware_layers,
        )
        try:
            assistant_payload = load_yaml_layers(self.voice_assistant_layers)
            device_payload = load_yaml_layers(self.device_hardware_layers)
            voice_audio = device_payload.get("voice_audio", {})
            if not isinstance(voice_audio, dict):
                voice_audio = {}

            payload = deep_merge_mappings(assistant_payload, {"audio": voice_audio})

            self.voice_settings = build_config_model(VoiceConfig, payload)
            self.voice_config = config_to_dict(self.voice_settings)
            self._refresh_runtime_settings()

            if self.voice_config_loaded:
                logger.info("Voice configuration loaded successfully")
            else:
                logger.warning("No authored voice config found; using typed defaults")

            return self.voice_config_loaded
        except Exception:
            logger.exception("Error loading voice config")
            self.voice_settings = VoiceConfig()
            self.voice_config = config_to_dict(self.voice_settings)
            self.voice_config_loaded = False
            self._refresh_runtime_settings()
            return False

    def load_network_config(self) -> bool:
        """Load the typed network config from domain-owned cellular layers."""

        self.network_config_loaded = config_loaded(self.network_cellular_layers)
        try:
            payload = load_yaml_layers(self.network_cellular_layers)
            self.network_settings = build_config_model(
                NetworkConfig, payload.get("network", payload)
            )
            self.network_config = config_to_dict(self.network_settings)
            self._refresh_runtime_settings()

            if self.network_config_loaded:
                logger.info("Network configuration loaded successfully")
            else:
                logger.warning("No authored network config found; using typed defaults")

            return self.network_config_loaded
        except Exception:
            logger.exception("Error loading network config")
            self.network_settings = NetworkConfig()
            self.network_config = config_to_dict(self.network_settings)
            self.network_config_loaded = False
            self._refresh_runtime_settings()
            return False

    def load_communication_config(self) -> bool:
        """Load the typed communication config from calling/messaging/device/secrets files."""

        self.device_hardware_config_loaded = config_loaded(self.device_hardware_layers)
        self.communication_config_loaded = config_loaded(
            self.communication_calling_layers,
            self.communication_messaging_layers,
            self.device_hardware_layers,
        )
        self.communication_secrets_loaded = self.communication_secrets_file.exists()

        try:
            calling_payload = load_yaml_layers(self.communication_calling_layers)
            messaging_payload = load_yaml_layers(self.communication_messaging_layers)
            device_payload = load_yaml_layers(self.device_hardware_layers)
            secrets_payload = load_yaml_mapping(self.communication_secrets_file)

            self._validate_secret_boundary(calling_payload, source="communication/calling.yaml")
            self._validate_secret_boundary(
                messaging_payload,
                source="communication/messaging.yaml",
            )
            self._validate_secret_boundary(device_payload, source="device/hardware.yaml")

            communication_audio = device_payload.get("communication_audio", {})
            if not isinstance(communication_audio, dict):
                communication_audio = {}

            payload = merge_layer_groups(
                self.communication_calling_layers,
                self.communication_messaging_layers,
            )
            payload = deep_merge_mappings(payload, {"audio": communication_audio})
            payload = deep_merge_mappings(payload, secrets_payload)

            self.communication_settings = build_config_model(CommunicationConfig, payload)
            self.communication_config = config_to_dict(self.communication_settings)
            self._refresh_runtime_settings()

            if self.communication_config_loaded:
                logger.info("Communication configuration loaded successfully")
            else:
                logger.warning("No authored communication config found; using typed defaults")

            if not self.communication_secrets_loaded:
                logger.info(
                    "Communication secrets file not found at {}; env vars remain available",
                    self.communication_secrets_file,
                )

            logger.debug("SIP server: {}", self.get_sip_server())
            logger.debug("SIP identity: {}", self.get_sip_identity())
            return self.communication_config_loaded or self.communication_secrets_loaded
        except Exception:
            logger.exception("Error loading communication config")
            self.communication_settings = CommunicationConfig()
            self.communication_config = config_to_dict(self.communication_settings)
            self.communication_config_loaded = False
            self.communication_secrets_loaded = False
            self._refresh_runtime_settings()
            return False

    def load_people_config(self) -> bool:
        """Load the typed people-data path config."""

        self.people_config_loaded = config_loaded(self.people_directory_layers)
        try:
            payload = load_yaml_layers(self.people_directory_layers)
            self.people_settings = build_config_model(PeopleDirectoryConfig, payload)
            self._refresh_runtime_settings()
            return self.people_config_loaded
        except Exception:
            logger.exception("Error loading people config")
            self.people_settings = PeopleDirectoryConfig()
            self.people_config_loaded = False
            self._refresh_runtime_settings()
            return False

    def load_cloud_config(self) -> bool:
        """Load cloud/backend tracked config plus runtime-only device secrets."""

        self.cloud_config_loaded = config_loaded(self.cloud_backend_layers)
        self.cloud_secrets_runtime_file = (
            self.cloud_secrets_file
            if self.cloud_secrets_file.exists()
            else SYSTEM_CLOUD_SECRETS_FILE
        )
        self.cloud_secrets_loaded = self.cloud_secrets_runtime_file.exists()
        self.cloud_secrets_error = ""
        try:
            backend_payload = load_yaml_layers(self.cloud_backend_layers)
            secrets_payload: dict[str, Any] = {}
            if self.cloud_secrets_loaded:
                secrets_payload = load_yaml_mapping(self.cloud_secrets_runtime_file)

            merged_payload = {
                "backend": backend_payload.get("backend", backend_payload),
                "secrets": secrets_payload.get("secrets", secrets_payload),
            }
            self.cloud_settings = build_config_model(CloudConfig, merged_payload)

            device_id = self.cloud_settings.secrets.device_id.strip()
            device_secret = self.cloud_settings.secrets.device_secret.strip()
            if (device_id and not device_secret) or (device_secret and not device_id):
                self.cloud_secrets_error = (
                    "Provisioning file must contain both device_id and device_secret"
                )

            self._refresh_runtime_settings()

            if self.cloud_config_loaded:
                logger.info("Cloud backend configuration loaded successfully")
            else:
                logger.info("No cloud backend config found; backend connectivity disabled")
            if self.cloud_secrets_loaded:
                logger.info(
                    "Cloud provisioning secrets loaded successfully from {}",
                    self.cloud_secrets_runtime_file,
                )

            return self.cloud_config_loaded or self.cloud_secrets_loaded
        except Exception:
            logger.exception("Error loading cloud config")
            self.cloud_settings = CloudConfig()
            self.cloud_config_loaded = False
            self.cloud_secrets_loaded = False
            self.cloud_secrets_error = "Failed to load cloud configuration"
            self._refresh_runtime_settings()
            return False

    def load_backend_config(self) -> bool:
        """Compatibility alias for older telemetry-only callers."""

        return self.load_cloud_config()

    def get_cloud_settings(self) -> CloudConfig:
        """Return the typed cloud settings."""

        return self.cloud_settings

    def get_backend_settings(self) -> Any:
        """Compatibility alias returning just the backend subsection."""

        return self.cloud_settings.backend

    def get_cloud_device_id(self) -> str:
        return self.cloud_settings.secrets.device_id

    def get_cloud_device_secret(self) -> str:
        return self.cloud_settings.secrets.device_secret

    def get_cloud_cache_file(self) -> str:
        return self.cloud_settings.backend.cache_file

    def get_cloud_status_file(self) -> str:
        return self.cloud_settings.backend.status_file

    def get_max_output_volume(self) -> int:
        value = self._cloud_override_values.get("audio.max_volume", 80)
        return max(0, min(100, int(value)))

    def apply_cloud_overrides(self, payload: dict[str, Any]) -> list[str]:
        """Apply recognized runtime-only cloud overrides and return unapplied keys."""

        if not isinstance(payload, dict):
            return ["<invalid-payload>"]

        unapplied: list[str] = []

        audio_payload = payload.get("audio", {})
        if isinstance(audio_payload, dict):
            if "max_volume" in audio_payload:
                try:
                    self._cloud_override_values["audio.max_volume"] = max(
                        0,
                        min(100, int(audio_payload["max_volume"])),
                    )
                except (TypeError, ValueError):
                    unapplied.append("audio.max_volume")
            if "default_volume" in audio_payload:
                try:
                    self.media_settings.music.default_volume = max(
                        0,
                        min(100, int(audio_payload["default_volume"])),
                    )
                except (TypeError, ValueError):
                    unapplied.append("audio.default_volume")
        elif "audio" in payload:
            unapplied.append("audio")

        messaging_payload = payload.get("messaging", {})
        if isinstance(messaging_payload, dict):
            if "voice_note_max_duration_seconds" in messaging_payload:
                try:
                    self.communication_settings.messaging.voice_note_max_duration_seconds = max(
                        1,
                        int(messaging_payload["voice_note_max_duration_seconds"]),
                    )
                except (TypeError, ValueError):
                    unapplied.append("messaging.voice_note_max_duration_seconds")
        elif "messaging" in payload:
            unapplied.append("messaging")

        recognized_top_level = {"audio", "messaging", "config_version"}
        for key in payload:
            if key not in recognized_top_level:
                unapplied.append(str(key))

        self._refresh_runtime_settings()
        return sorted(set(unapplied))

    def get_app_settings(self) -> YoyoPodConfig:
        """Return the composed typed app settings."""

        return self.app_settings

    def get_voice_settings(self) -> VoiceConfig:
        """Return the composed typed voice settings."""

        return self.voice_settings

    def get_media_settings(self) -> MediaConfig:
        """Return the composed typed media settings."""

        return self.media_settings

    def get_power_settings(self) -> PowerConfig:
        """Return the composed typed power settings."""

        return self.power_settings

    def get_network_settings(self) -> NetworkConfig:
        """Return the composed typed network settings."""

        return self.network_settings

    def get_communication_settings(self) -> CommunicationConfig:
        """Return the composed typed communication settings."""

        return self.communication_settings

    def get_people_settings(self) -> PeopleDirectoryConfig:
        """Return the typed people directory settings."""

        return self.people_settings

    def get_runtime_settings(self) -> YoyoPodRuntimeConfig:
        """Return the single typed runtime model consumed by the app."""

        return self.runtime_settings

    def get_app_config_dict(self) -> dict[str, Any]:
        """Return the plain-dict form of the composed app settings."""

        return dict(self.app_config)

    def get_media_config_dict(self) -> dict[str, Any]:
        """Return the plain-dict form of the composed media settings."""

        return dict(self.media_config)

    def get_power_config_dict(self) -> dict[str, Any]:
        """Return the plain-dict form of the composed power settings."""

        return dict(self.power_config)

    def get_runtime_config_dict(self) -> dict[str, Any]:
        """Return the plain-dict form of the composed runtime settings."""

        return dict(self.runtime_config)

    def resolve_runtime_path(self, path_value: str | Path) -> Path:
        """Resolve a repo-relative runtime path from the active config root."""

        path = Path(path_value)
        if path.is_absolute():
            return path
        base_dir = self.config_dir.parent if self.config_dir.name == "config" else self.config_dir
        return base_dir / path

    def set_voice_capture_device_id(self, device_id: str | None) -> bool:
        """Persist the capture device selector used by local voice interactions."""

        value = (device_id or "").strip()
        if "\n" in value or "\r" in value:
            raise ValueError("Invalid ALSA device id (contains newline)")
        if not self._save_device_hardware_layer_patch(
            {"voice_audio": {"capture_device_id": value}}
        ):
            return False
        self.voice_settings.audio.capture_device_id = value
        self.voice_config.setdefault("audio", {})["capture_device_id"] = value
        self._refresh_runtime_settings()
        return True

    def set_voice_speaker_device_id(self, device_id: str | None) -> bool:
        """Persist the playback device selector used by local voice interactions."""

        value = (device_id or "").strip()
        if "\n" in value or "\r" in value:
            raise ValueError("Invalid ALSA device id (contains newline)")
        if not self._save_device_hardware_layer_patch(
            {"voice_audio": {"speaker_device_id": value}}
        ):
            return False
        self.voice_settings.audio.speaker_device_id = value
        self.voice_config.setdefault("audio", {})["speaker_device_id"] = value
        self._refresh_runtime_settings()
        return True

    def get_voice_speaker_device_id(self) -> str:
        """Return the configured local-voice playback selector."""

        return self.voice_settings.audio.speaker_device_id

    def get_voice_capture_device_id(self) -> str:
        """Return the configured local-voice capture selector."""

        return self.voice_settings.audio.capture_device_id

    def get_sip_server(self) -> str:
        return self.communication_settings.calling.account.sip_server

    def get_sip_username(self) -> str:
        return self.communication_settings.calling.account.sip_username

    def get_sip_password(self) -> str:
        return self.communication_settings.secrets.sip_password

    def get_sip_password_ha1(self) -> str:
        return self.communication_settings.secrets.sip_password_ha1

    def get_sip_identity(self) -> str:
        return self.communication_settings.calling.account.sip_identity

    def get_voip_factory_config_path(self) -> str:
        return self.communication_settings.integrations.liblinphone_factory_config_path

    def get_transport(self) -> str:
        return self.communication_settings.calling.account.transport

    def get_display_name(self) -> str:
        return self.communication_settings.calling.account.display_name

    def get_stun_server(self) -> str:
        return self.communication_settings.calling.network.stun_server

    def get_file_transfer_server_url(self) -> str:
        return self.communication_settings.messaging.file_transfer_server_url

    def get_conference_factory_uri(self) -> str:
        return self.communication_settings.messaging.conference_factory_uri

    def get_lime_server_url(self) -> str:
        return self.communication_settings.messaging.lime_server_url

    def get_voip_iterate_interval_ms(self) -> int:
        return self.communication_settings.messaging.iterate_interval_ms

    def get_message_store_dir(self) -> str:
        return self.communication_settings.messaging.message_store_dir

    def get_voice_note_store_dir(self) -> str:
        return self.communication_settings.messaging.voice_note_store_dir

    def get_voice_note_max_duration_seconds(self) -> int:
        return self.communication_settings.messaging.voice_note_max_duration_seconds

    def get_auto_download_incoming_voice_recordings(self) -> bool:
        return self.communication_settings.messaging.auto_download_incoming_voice_recordings

    def get_auto_answer(self) -> bool:
        return self.communication_settings.calling.auto_answer

    def get_call_timeout(self) -> int:
        return self.communication_settings.calling.call_timeout

    def get_call_history_file(self) -> str:
        return self.communication_settings.calling.call_history_file

    def get_playback_device_id(self) -> str:
        return self.communication_settings.audio.playback_device_id

    def get_ringer_device_id(self) -> str:
        configured = self.communication_settings.audio.ringer_device_id
        return configured or self.get_playback_device_id()

    def get_capture_device_id(self) -> str:
        return self.communication_settings.audio.capture_device_id

    def get_media_device_id(self) -> str:
        configured = self.communication_settings.audio.media_device_id
        return configured or self.get_playback_device_id()

    def get_mic_gain(self) -> int:
        return self.communication_settings.audio.mic_gain

    def get_default_output_volume(self) -> int:
        return self.media_settings.music.default_volume

    def get_media_alsa_device(self) -> str:
        return self.media_settings.audio.alsa_device

    def get_speaker_test_path(self) -> str:
        return self.media_settings.music.speaker_test_path

    def get_recent_tracks_file(self) -> str:
        return self.media_settings.music.recent_tracks_file

    def get_ring_output_device(self) -> str:
        ring_output = self.communication_settings.audio.ring_output_device
        if ring_output:
            return ring_output

        playback_device = self.get_playback_device_id()
        if playback_device.startswith("ALSA:"):
            return playback_device.split(":", 1)[1].strip()
        return playback_device or "default"

    def get_people_contacts_file(self) -> str:
        return str(self.resolve_runtime_path(self.people_settings.contacts_file))

    def get_people_contacts_seed_file(self) -> str:
        return str(self.resolve_runtime_path(self.people_settings.contacts_seed_file))

    def reload(self) -> None:
        """Reload all authored config from disk."""

        logger.info("Reloading configuration...")
        self.load_app_config()
        self.load_media_config()
        self.load_power_config()
        self.load_network_config()
        self.load_voice_config()
        self.load_communication_config()
        self.load_people_config()
        self.load_cloud_config()
