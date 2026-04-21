"""Regression coverage for relocated core module compatibility shims."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

from yoyopod.audio.music.models import Track as MusicTrack
from yoyopod.app_context import (
    AppContext,
    InteractionProfile as AppContextInteractionProfile,
    PlaybackQueue as AppContextPlaybackQueue,
    Track as AppContextTrack,
)
from yoyopod.core import AppContext as CoreAppContext
from yoyopod.core.event_bus import EventBus as CoreEventBus
from yoyopod.core.event_bus import EventHandler as CoreEventHandler
from yoyopod.core.events import TrackChangedEvent as CoreTrackChangedEvent
from yoyopod.core.fsm import CallFSM as CoreCallFSM
from yoyopod.core.fsm import CallInterruptionPolicy as CoreCallInterruptionPolicy
from yoyopod.core.fsm import MusicFSM as CoreMusicFSM
from yoyopod.core.runtime_state import VoiceState as CoreVoiceState
from yoyopod.core.setup_contract import (
    RUNTIME_REQUIRED_CONFIG_FILES as CORE_RUNTIME_REQUIRED_CONFIG_FILES,
)
from yoyopod.backends.cloud import CloudClientError as BackendCloudClientError
from yoyopod.backends.cloud import CloudDeviceClient as BackendCloudDeviceClient
from yoyopod.backends.cloud import DeviceMqttClient as BackendDeviceMqttClient
from yoyopod.backends.power import PiSugarBackend as BackendPiSugarBackend
from yoyopod.backends.power import PiSugarWatchdog as BackendPiSugarWatchdog
from yoyopod.backends.voice import AlsaOutputPlayer as BackendAlsaOutputPlayer
from yoyopod.backends.voice import (
    EspeakNgTextToSpeechBackend as BackendEspeakNgTextToSpeechBackend,
)
from yoyopod.backends.voice import (
    SubprocessAudioCaptureBackend as BackendSubprocessAudioCaptureBackend,
)
from yoyopod.backends.voice import (
    VoskSpeechToTextBackend as BackendVoskSpeechToTextBackend,
)
from yoyopod.backends.location import GpsReader as BackendGpsReader
from yoyopod.backends.network import AtCommandSet as BackendAtCommandSet
from yoyopod.backends.network import PppProcess as BackendPppProcess
from yoyopod.backends.network import SerialTransport as BackendSerialTransport
from yoyopod.backends.network import Sim7600Backend as BackendSim7600Backend
from yoyopod.backends.network import TransportError as BackendTransportError
from yoyopod.backends.voip import LiblinphoneBackend as BackendLiblinphoneBackend
from yoyopod.backends.voip import LiblinphoneBinding as BackendLiblinphoneBinding
from yoyopod.backends.voip import MockVoIPBackend as BackendMockVoIPBackend
from yoyopod.backends.voip import VoIPBackend as BackendVoIPBackend
from yoyopod.backends.voip import VoIPIterateMetrics as BackendVoIPIterateMetrics
from yoyopod.integrations.call import CallState as IntegrationCallState
from yoyopod.integrations.call import CallHistoryEntry as IntegrationCallHistoryEntry
from yoyopod.integrations.call import CallHistoryStore as IntegrationCallHistoryStore
from yoyopod.integrations.call import MessagingService as IntegrationMessagingService
from yoyopod.integrations.call import MessageDeliveryState as IntegrationMessageDeliveryState
from yoyopod.integrations.call import RegistrationState as IntegrationRegistrationState
from yoyopod.integrations.call import VoIPConfig as IntegrationVoIPConfig
from yoyopod.integrations.call import VoIPManager as IntegrationVoIPManager
from yoyopod.integrations.call import VoIPMessageRecord as IntegrationVoIPMessageRecord
from yoyopod.integrations.call import VoIPMessageStore as IntegrationVoIPMessageStore
from yoyopod.integrations.call import VoiceNoteDraft as IntegrationVoiceNoteDraft
from yoyopod.integrations.power import BatteryState as IntegrationBatteryState
from yoyopod.integrations.power import PowerManager as IntegrationPowerManager
from yoyopod.integrations.power import PowerSnapshot as IntegrationPowerSnapshot
from yoyopod.integrations.power import RTCState as IntegrationRTCState
from yoyopod.integrations.network import GpsCoordinate as IntegrationGpsCoordinate
from yoyopod.integrations.network import ModemPhase as IntegrationModemPhase
from yoyopod.integrations.network import ModemState as IntegrationModemState
from yoyopod.integrations.network import NetworkManager as IntegrationNetworkManager
from yoyopod.integrations.network import SignalInfo as IntegrationSignalInfo
from yoyopod.integrations.contacts.cloud_sync import (
    build_cloud_contact as ContactsBuildCloudContact,
)
from yoyopod.integrations.contacts.directory import (
    PeopleDirectory as ContactsPeopleDirectory,
)
from yoyopod.integrations.contacts.directory import PeopleManager as ContactsPeopleManager
from yoyopod.integrations.contacts.models import Contact as ContactsContact
from yoyopod.integrations.contacts.models import (
    contacts_from_mapping as contacts_from_mapping_new,
)
from yoyopod.integrations.contacts.models import contacts_to_mapping as contacts_to_mapping_new
from yoyopod.integrations.cloud.manager import CloudManager as IntegrationCloudManager
from yoyopod.integrations.cloud.models import CloudAccessToken as IntegrationCloudAccessToken
from yoyopod.integrations.cloud.models import (
    CloudStatusSnapshot as IntegrationCloudStatusSnapshot,
)
from yoyopod.integrations.voice import VoiceCaptureRequest as IntegrationVoiceCaptureRequest
from yoyopod.integrations.voice import VoiceCaptureResult as IntegrationVoiceCaptureResult
from yoyopod.integrations.voice import VoiceManager as IntegrationVoiceManager
from yoyopod.integrations.voice import VoiceService as IntegrationVoiceService
from yoyopod.integrations.voice import VoiceSettings as IntegrationVoiceSettings
from yoyopod.integrations.voice import VoiceTranscript as IntegrationVoiceTranscript
from yoyopod.runtime_state import PlaybackQueue as RuntimeStatePlaybackQueue
from yoyopod.runtime_state import Track as RuntimeStateTrack
from yoyopod.event_bus import EventBus, EventHandler
from yoyopod.events import CallState, RegistrationState, Track, TrackChangedEvent
from yoyopod.fsm import MusicFSM
from yoyopod.cloud import CloudAccessToken as LegacyCloudAccessToken
from yoyopod.cloud import CloudClientError as LegacyCloudClientError
from yoyopod.cloud import CloudDeviceClient as LegacyCloudDeviceClient
from yoyopod.cloud import CloudManager as LegacyCloudManager
from yoyopod.cloud import CloudStatusSnapshot as LegacyCloudStatusSnapshot
from yoyopod.cloud import DeviceMqttClient as LegacyDeviceMqttClient
from yoyopod.network import GpsCoordinate as LegacyGpsCoordinate
from yoyopod.network import ModemPhase as LegacyModemPhase
from yoyopod.network import ModemState as LegacyModemState
from yoyopod.network import NetworkManager as LegacyNetworkManager
from yoyopod.network import SignalInfo as LegacySignalInfo
from yoyopod.network import Sim7600Backend as LegacySim7600Backend
from yoyopod.communication.calling import CallHistoryEntry as LegacyCallHistoryEntry
from yoyopod.communication.calling import CallHistoryStore as LegacyCallHistoryStore
from yoyopod.communication.calling import VoIPManager as LegacyVoIPManager
from yoyopod.communication.calling import VoiceNoteDraft as LegacyVoiceNoteDraft
from yoyopod.communication.calling.backend import (
    LiblinphoneBackend as LegacyCallingLiblinphoneBackend,
)
from yoyopod.communication.calling.backend import MockVoIPBackend as LegacyCallingMockVoIPBackend
from yoyopod.communication.calling.backend import VoIPBackend as LegacyCallingVoIPBackend
from yoyopod.communication.calling.backend import (
    VoIPIterateMetrics as LegacyCallingVoIPIterateMetrics,
)
from yoyopod.communication.calling.messaging import MessagingService as LegacyMessagingService
from yoyopod.network.at_commands import AtCommandSet as LegacyAtCommandSet
from yoyopod.network.backend import Sim7600Backend as LegacyBackendSim7600Backend
from yoyopod.network.gps import GpsReader as LegacyGpsReader
from yoyopod.network.ppp import PppProcess as LegacyPppProcess
from yoyopod.network.transport import SerialTransport as LegacySerialTransport
from yoyopod.network.transport import TransportError as LegacyTransportError
from yoyopod.people import Contact as LegacyContact
from yoyopod.people import PeopleDirectory as LegacyPeopleDirectory
from yoyopod.people import PeopleManager as LegacyPeopleManager
from yoyopod.people import build_cloud_contact as legacy_build_cloud_contact
from yoyopod.people import contacts_from_mapping as legacy_contacts_from_mapping
from yoyopod.people import contacts_to_mapping as legacy_contacts_to_mapping
from yoyopod.power import PowerManager as LegacyPowerManager
from yoyopod.power import PowerSnapshot as LegacyPowerSnapshot
from yoyopod.power.backend import PiSugarBackend as LegacyPiSugarBackend
from yoyopod.power.models import BatteryState as LegacyBatteryState
from yoyopod.power.models import RTCState as LegacyRTCState
from yoyopod.power.watchdog import PiSugarWatchdog as LegacyPiSugarWatchdog
from yoyopod.runtime_state import VoiceState
from yoyopod.setup_contract import Path as SetupContractPath
from yoyopod.setup_contract import RUNTIME_REQUIRED_CONFIG_FILES
from yoyopod.ui.input.hal import InteractionProfile
from yoyopod.voice import VoiceManager as LegacyVoiceManager
from yoyopod.voice import VoiceService as LegacyVoiceService
from yoyopod.voice import VoiceSettings as LegacyVoiceSettings
from yoyopod.voice.capture import (
    SubprocessAudioCaptureBackend as LegacySubprocessAudioCaptureBackend,
)
from yoyopod.voice.models import VoiceCaptureRequest as LegacyVoiceCaptureRequest
from yoyopod.voice.models import VoiceCaptureResult as LegacyVoiceCaptureResult
from yoyopod.voice.models import VoiceTranscript as LegacyVoiceTranscript
from yoyopod.voice.output import AlsaOutputPlayer as LegacyAlsaOutputPlayer
from yoyopod.voice.stt import VoskSpeechToTextBackend as LegacyVoskSpeechToTextBackend
from yoyopod.voice.tts import (
    EspeakNgTextToSpeechBackend as LegacyEspeakNgTextToSpeechBackend,
)
from yoyopod.communication.integrations.liblinphone import (
    LiblinphoneBackend as LegacyLiblinphoneBackend,
)
from yoyopod.communication.integrations.liblinphone import (
    LiblinphoneBinding as LegacyLiblinphoneBinding,
)
from yoyopod.communication.integrations.liblinphone_binding import (
    LiblinphoneBinding as LegacyCompatLiblinphoneBinding,
)
from yoyopod.communication.messaging import VoIPMessageStore as LegacyVoIPMessageStore
from yoyopod.communication.models import CallState as LegacyCommunicationCallState
from yoyopod.communication.models import MessageDeliveryState as LegacyMessageDeliveryState
from yoyopod.communication.models import RegistrationState as LegacyCommunicationRegistrationState
from yoyopod.communication.models import VoIPConfig as LegacyVoIPConfig
from yoyopod.communication.models import VoIPMessageRecord as LegacyVoIPMessageRecord
from yoyopod import EventBus as RootEventBus
from yoyopod import CallFSM as RootCallFSM
from yoyopod import MusicFSM as RootMusicFSM


def test_legacy_core_import_paths_resolve_to_relocated_symbols() -> None:
    """Legacy top-level imports should remain valid after the core package split."""

    assert AppContext is CoreAppContext
    assert EventBus is CoreEventBus
    assert EventHandler is CoreEventHandler
    assert CallState is IntegrationCallState
    assert RegistrationState is IntegrationRegistrationState
    assert Track is MusicTrack
    assert TrackChangedEvent is CoreTrackChangedEvent
    assert MusicFSM is CoreMusicFSM
    assert VoiceState is CoreVoiceState
    assert RUNTIME_REQUIRED_CONFIG_FILES == CORE_RUNTIME_REQUIRED_CONFIG_FILES
    assert AppContextPlaybackQueue is RuntimeStatePlaybackQueue
    assert AppContextTrack is RuntimeStateTrack
    assert AppContextInteractionProfile is InteractionProfile
    assert SetupContractPath is Path
    assert RootEventBus is EventBus
    assert RootMusicFSM is MusicFSM
    assert RootCallFSM is CoreCallFSM


def test_legacy_people_import_paths_resolve_to_relocated_contacts_symbols() -> None:
    """Legacy people imports should keep pointing at the new contacts ownership seam."""

    assert LegacyContact is ContactsContact
    assert LegacyPeopleManager is ContactsPeopleManager
    assert LegacyPeopleDirectory is ContactsPeopleDirectory
    assert legacy_build_cloud_contact is ContactsBuildCloudContact
    assert legacy_contacts_from_mapping is contacts_from_mapping_new
    assert legacy_contacts_to_mapping is contacts_to_mapping_new


def test_legacy_call_import_paths_resolve_to_relocated_symbols() -> None:
    """Legacy call imports should keep pointing at the canonical call seam."""

    assert LegacyCommunicationCallState is IntegrationCallState
    assert LegacyCallHistoryEntry is IntegrationCallHistoryEntry
    assert LegacyCallHistoryStore is IntegrationCallHistoryStore
    assert LegacyMessagingService is IntegrationMessagingService
    assert LegacyMessageDeliveryState is IntegrationMessageDeliveryState
    assert LegacyCommunicationRegistrationState is IntegrationRegistrationState
    assert LegacyVoIPConfig is IntegrationVoIPConfig
    assert LegacyVoIPManager is IntegrationVoIPManager
    assert LegacyVoIPMessageRecord is IntegrationVoIPMessageRecord
    assert LegacyVoIPMessageStore is IntegrationVoIPMessageStore
    assert LegacyVoiceNoteDraft is IntegrationVoiceNoteDraft


def test_legacy_voip_backend_import_paths_resolve_to_relocated_symbols() -> None:
    """Legacy VoIP backend imports should keep pointing at the canonical backend seam."""

    assert LegacyCallingLiblinphoneBackend is BackendLiblinphoneBackend
    assert LegacyCallingMockVoIPBackend is BackendMockVoIPBackend
    assert LegacyCallingVoIPBackend is BackendVoIPBackend
    assert LegacyCallingVoIPIterateMetrics is BackendVoIPIterateMetrics
    assert LegacyLiblinphoneBackend is BackendLiblinphoneBackend
    assert LegacyLiblinphoneBinding is BackendLiblinphoneBinding
    assert LegacyCompatLiblinphoneBinding is BackendLiblinphoneBinding


def test_legacy_cloud_import_paths_resolve_to_relocated_cloud_symbols() -> None:
    """Legacy cloud imports should keep pointing at the new cloud ownership seams."""

    assert LegacyCloudAccessToken is IntegrationCloudAccessToken
    assert LegacyCloudStatusSnapshot is IntegrationCloudStatusSnapshot
    assert LegacyCloudClientError is BackendCloudClientError
    assert LegacyCloudDeviceClient is BackendCloudDeviceClient
    assert LegacyDeviceMqttClient is BackendDeviceMqttClient
    assert LegacyCloudManager is IntegrationCloudManager


def test_legacy_power_import_paths_resolve_to_relocated_symbols() -> None:
    """Legacy power imports should keep pointing at the canonical power seam."""

    assert LegacyBatteryState is IntegrationBatteryState
    assert LegacyPowerManager is IntegrationPowerManager
    assert LegacyPowerSnapshot is IntegrationPowerSnapshot
    assert LegacyRTCState is IntegrationRTCState
    assert LegacyPiSugarBackend is BackendPiSugarBackend
    assert LegacyPiSugarWatchdog is BackendPiSugarWatchdog


def test_legacy_voice_import_paths_resolve_to_relocated_symbols() -> None:
    """Legacy voice imports should keep pointing at the canonical voice seam."""

    assert LegacyVoiceCaptureRequest is IntegrationVoiceCaptureRequest
    assert LegacyVoiceCaptureResult is IntegrationVoiceCaptureResult
    assert LegacyVoiceManager is IntegrationVoiceManager
    assert LegacyVoiceService is IntegrationVoiceService
    assert LegacyVoiceSettings is IntegrationVoiceSettings
    assert LegacyVoiceTranscript is IntegrationVoiceTranscript
    assert LegacySubprocessAudioCaptureBackend is BackendSubprocessAudioCaptureBackend
    assert LegacyAlsaOutputPlayer is BackendAlsaOutputPlayer
    assert LegacyVoskSpeechToTextBackend is BackendVoskSpeechToTextBackend
    assert LegacyEspeakNgTextToSpeechBackend is BackendEspeakNgTextToSpeechBackend


def test_legacy_network_backend_import_paths_resolve_to_relocated_symbols() -> None:
    """Legacy low-level network imports should resolve to the relocated backends."""

    assert LegacyAtCommandSet is BackendAtCommandSet
    assert LegacyPppProcess is BackendPppProcess
    assert LegacySerialTransport is BackendSerialTransport
    assert LegacyTransportError is BackendTransportError
    assert LegacyGpsReader is BackendGpsReader
    assert LegacyBackendSim7600Backend is BackendSim7600Backend
    assert LegacySim7600Backend is BackendSim7600Backend


def test_legacy_network_public_import_paths_resolve_to_relocated_symbols() -> None:
    """Legacy network manager/model imports should resolve to the canonical integration seam."""

    assert LegacyGpsCoordinate is IntegrationGpsCoordinate
    assert LegacyModemPhase is IntegrationModemPhase
    assert LegacyModemState is IntegrationModemState
    assert LegacyNetworkManager is IntegrationNetworkManager
    assert LegacySignalInfo is IntegrationSignalInfo


def test_demo_entrypoints_keep_importing_legacy_shims(monkeypatch) -> None:
    """Demo modules that still import legacy paths should remain importable."""

    class DummyMopidyClient:
        pass

    class DummyRegistrationState:
        pass

    class DummyVoIPConfig:
        pass

    class DummyVoIPManager:
        pass

    mopidy_module = types.ModuleType("yoyopod.audio.mopidy_client")
    mopidy_module.MopidyClient = DummyMopidyClient
    monkeypatch.setitem(sys.modules, "yoyopod.audio.mopidy_client", mopidy_module)

    voip_module = types.ModuleType("yoyopod.voip")
    voip_module.RegistrationState = DummyRegistrationState
    voip_module.VoIPConfig = DummyVoIPConfig
    voip_module.VoIPManager = DummyVoIPManager
    monkeypatch.setitem(sys.modules, "yoyopod.voip", voip_module)

    for module_name in (
        "demos.demo_runtime_state",
        "demos.demo_interactive",
        "demos.demo_mopidy",
        "demos.demo_playlists",
        "demos.demo_voip",
    ):
        sys.modules.pop(module_name, None)

    runtime_demo = importlib.import_module("demos.demo_runtime_state")
    interactive_demo = importlib.import_module("demos.demo_interactive")
    mopidy_demo = importlib.import_module("demos.demo_mopidy")
    playlist_demo = importlib.import_module("demos.demo_playlists")
    voip_demo = importlib.import_module("demos.demo_voip")

    assert runtime_demo.AppContext is AppContext
    assert runtime_demo.CallFSM is CoreCallFSM
    assert runtime_demo.CallInterruptionPolicy is CoreCallInterruptionPolicy
    assert runtime_demo.MusicFSM is MusicFSM
    assert interactive_demo.AppContext is AppContext
    assert mopidy_demo.AppContext is AppContext
    assert playlist_demo.AppContext is AppContext
    assert voip_demo.AppContext is AppContext
