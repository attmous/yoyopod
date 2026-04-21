"""Core orchestration primitives for YoyoPod.

Legacy top-level modules such as ``yoyopod.app_context``, ``yoyopod.event_bus``,
``yoyopod.events``, ``yoyopod.fsm``, ``yoyopod.runtime_state``, and
``yoyopod.setup_contract`` remain as thin compatibility shims that re-export
these symbols.
"""

from __future__ import annotations

from typing import Any

_PUBLIC_EXPORTS = {
    "ActiveVoiceNoteState": ("yoyopod.core.runtime_state", "ActiveVoiceNoteState"),
    "AudioDeviceCatalog": ("yoyopod.core.hardware", "AudioDeviceCatalog"),
    "AudioFocusGrantedEvent": ("yoyopod.core.events", "AudioFocusGrantedEvent"),
    "AudioFocusLostEvent": ("yoyopod.core.events", "AudioFocusLostEvent"),
    "AppContext": ("yoyopod.core.app_context", "AppContext"),
    "BackendStoppedEvent": ("yoyopod.core.events", "BackendStoppedEvent"),
    "Bus": ("yoyopod.core.bus", "Bus"),
    "CallEndedEvent": ("yoyopod.core.events", "CallEndedEvent"),
    "CallFSM": ("yoyopod.core.fsm", "CallFSM"),
    "CallInterruptionPolicy": ("yoyopod.core.fsm", "CallInterruptionPolicy"),
    "CallSessionState": ("yoyopod.core.fsm", "CallSessionState"),
    "CallStateChangedEvent": ("yoyopod.core.events", "CallStateChangedEvent"),
    "DiagnosticsRuntime": ("yoyopod.core.diagnostics", "DiagnosticsRuntime"),
    "EventBus": ("yoyopod.core.event_bus", "EventBus"),
    "EventLogWriter": ("yoyopod.core.diagnostics", "EventLogWriter"),
    "FocusController": ("yoyopod.core.focus", "FocusController"),
    "IncomingCallEvent": ("yoyopod.core.events", "IncomingCallEvent"),
    "LifecycleEvent": ("yoyopod.core.events", "LifecycleEvent"),
    "LogBuffer": ("yoyopod.core.logbuffer", "LogBuffer"),
    "MainThreadScheduler": ("yoyopod.core.scheduler", "MainThreadScheduler"),
    "MediaRuntimeState": ("yoyopod.core.runtime_state", "MediaRuntimeState"),
    "MusicAvailabilityChangedEvent": (
        "yoyopod.core.events",
        "MusicAvailabilityChangedEvent",
    ),
    "MusicFSM": ("yoyopod.core.fsm", "MusicFSM"),
    "MusicState": ("yoyopod.core.fsm", "MusicState"),
    "NetworkGpsFixEvent": ("yoyopod.core.events", "NetworkGpsFixEvent"),
    "NetworkGpsNoFixEvent": ("yoyopod.core.events", "NetworkGpsNoFixEvent"),
    "NetworkModemReadyEvent": ("yoyopod.core.events", "NetworkModemReadyEvent"),
    "NetworkPppDownEvent": ("yoyopod.core.events", "NetworkPppDownEvent"),
    "NetworkPppUpEvent": ("yoyopod.core.events", "NetworkPppUpEvent"),
    "NetworkRegisteredEvent": ("yoyopod.core.events", "NetworkRegisteredEvent"),
    "NetworkRuntimeState": ("yoyopod.core.runtime_state", "NetworkRuntimeState"),
    "NetworkSignalUpdateEvent": ("yoyopod.core.events", "NetworkSignalUpdateEvent"),
    "PlaybackState": ("yoyopod.core.runtime_state", "PlaybackState"),
    "PlaybackStateChangedEvent": ("yoyopod.core.events", "PlaybackStateChangedEvent"),
    "PowerRuntimeState": ("yoyopod.core.runtime_state", "PowerRuntimeState"),
    "RUNTIME_REQUIRED_CONFIG_FILES": (
        "yoyopod.core.setup_contract",
        "RUNTIME_REQUIRED_CONFIG_FILES",
    ),
    "RecoveryAttemptCompletedEvent": (
        "yoyopod.core.events",
        "RecoveryAttemptCompletedEvent",
    ),
    "RecoveryAttemptedEvent": ("yoyopod.core.recovery", "RecoveryAttemptedEvent"),
    "RecoveryRuntime": ("yoyopod.core.recovery", "RecoveryRuntime"),
    "RecoverySupervisor": ("yoyopod.core.recovery", "RecoverySupervisor"),
    "ReleaseFocusCommand": ("yoyopod.core.focus", "ReleaseFocusCommand"),
    "RequestFocusCommand": ("yoyopod.core.focus", "RequestFocusCommand"),
    "RequestRecoveryCommand": ("yoyopod.core.recovery", "RequestRecoveryCommand"),
    "RegistrationChangedEvent": ("yoyopod.core.events", "RegistrationChangedEvent"),
    "RuntimeBootService": ("yoyopod.core.bootstrap", "RuntimeBootService"),
    "RuntimeLoopService": ("yoyopod.core.loop", "RuntimeLoopService"),
    "ScreenChangedEvent": ("yoyopod.core.events", "ScreenChangedEvent"),
    "ScreenRuntimeState": ("yoyopod.core.runtime_state", "ScreenRuntimeState"),
    "SETUP_TRACKED_CONFIG_FILES": (
        "yoyopod.core.setup_contract",
        "SETUP_TRACKED_CONFIG_FILES",
    ),
    "SnapshotCommand": ("yoyopod.core.diagnostics", "SnapshotCommand"),
    "Services": ("yoyopod.core.services", "Services"),
    "StateChangedEvent": ("yoyopod.core.events", "StateChangedEvent"),
    "StateValue": ("yoyopod.core.states", "StateValue"),
    "States": ("yoyopod.core.states", "States"),
    "TalkRuntimeState": ("yoyopod.core.runtime_state", "TalkRuntimeState"),
    "TrackChangedEvent": ("yoyopod.core.events", "TrackChangedEvent"),
    "UserActivityEvent": ("yoyopod.core.events", "UserActivityEvent"),
    "VoIPAvailabilityChangedEvent": ("yoyopod.core.events", "VoIPAvailabilityChangedEvent"),
    "VoipRuntimeState": ("yoyopod.core.runtime_state", "VoipRuntimeState"),
    "VoiceInteractionState": ("yoyopod.core.runtime_state", "VoiceInteractionState"),
    "VoiceState": ("yoyopod.core.runtime_state", "VoiceState"),
    "YoyoPodApp": ("yoyopod.core.application", "YoyoPodApp"),
    "format_device_label": ("yoyopod.core.hardware", "format_device_label"),
}


def __getattr__(name: str) -> Any:
    """Load public core exports lazily to avoid package import cycles."""

    try:
        module_name, attribute = _PUBLIC_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = __import__(module_name, fromlist=[attribute])
    return getattr(module, attribute)


__all__ = sorted(_PUBLIC_EXPORTS)
