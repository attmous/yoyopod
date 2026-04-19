"""Runtime composition config."""

from __future__ import annotations

from dataclasses import dataclass

from yoyopod.config.models.app import YoyoPodConfig
from yoyopod.config.models.cloud import CloudConfig
from yoyopod.config.models.communication import CommunicationConfig
from yoyopod.config.models.media import MediaConfig
from yoyopod.config.models.network import NetworkConfig
from yoyopod.config.models.people import PeopleDirectoryConfig
from yoyopod.config.models.power import PowerConfig
from yoyopod.config.models.voice import VoiceConfig
from yoyopod.config.models.core import config_value


@dataclass(slots=True)
class YoyoPodRuntimeConfig:
    """One typed runtime model composed from the canonical authored config topology."""

    app: YoyoPodConfig = config_value(default_factory=YoyoPodConfig)
    media: MediaConfig = config_value(default_factory=MediaConfig)
    power: PowerConfig = config_value(default_factory=PowerConfig)
    network: NetworkConfig = config_value(default_factory=NetworkConfig)
    voice: VoiceConfig = config_value(default_factory=VoiceConfig)
    communication: CommunicationConfig = config_value(default_factory=CommunicationConfig)
    people: PeopleDirectoryConfig = config_value(default_factory=PeopleDirectoryConfig)
    cloud: CloudConfig = config_value(default_factory=CloudConfig)
