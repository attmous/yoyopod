"""Core orchestration primitives for YoyoPod."""

from __future__ import annotations

from typing import Any

_PUBLIC_EXPORTS = {
    "ActiveVoiceNoteState": ("yoyopod.core.runtime_state", "ActiveVoiceNoteState"),
    "AudioDevice": ("yoyopod.core.audio_manager", "AudioDevice"),
    "AudioManager": ("yoyopod.core.audio_manager", "AudioManager"),
    "AudioDeviceCatalog": ("yoyopod.core.hardware", "AudioDeviceCatalog"),
    "AudioFocusGrantedEvent": ("yoyopod.core.events", "AudioFocusGrantedEvent"),
    "AudioFocusLostEvent": ("yoyopod.core.events", "AudioFocusLostEvent"),
    "AudioVolumeController": ("yoyopod.core.audio_volume", "AudioVolumeController"),
    "AppContext": ("yoyopod.core.app_context", "AppContext"),
    "AppRuntimeState": ("yoyopod.core.ui_state", "AppRuntimeState"),
    "BackendStoppedEvent": ("yoyopod.core.events", "BackendStoppedEvent"),
    "Bus": ("yoyopod.core.bus", "Bus"),
    "CoordinatorRuntime": ("yoyopod.core.ui_state", "CoordinatorRuntime"),
    "DiagnosticsRuntime": ("yoyopod.core.diagnostics", "DiagnosticsRuntime"),
    "EventLogWriter": ("yoyopod.core.diagnostics", "EventLogWriter"),
    "FocusController": ("yoyopod.core.focus", "FocusController"),
    "LifecycleEvent": ("yoyopod.core.events", "LifecycleEvent"),
    "LoggingRuntimeConfig": ("yoyopod.core.logging", "LoggingRuntimeConfig"),
    "LogBuffer": ("yoyopod.core.logbuffer", "LogBuffer"),
    "MainThreadScheduler": ("yoyopod.core.scheduler", "MainThreadScheduler"),
    "MediaRuntimeState": ("yoyopod.core.runtime_state", "MediaRuntimeState"),
    "MusicManager": ("yoyopod.core.audio_manager", "MusicManager"),
    "NetworkRuntimeState": ("yoyopod.core.runtime_state", "NetworkRuntimeState"),
    "OutputVolumeController": ("yoyopod.core.output_volume", "OutputVolumeController"),
    "PlaybackState": ("yoyopod.core.runtime_state", "PlaybackState"),
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
    "RuntimeRecoveryService": ("yoyopod.core.recovery", "RuntimeRecoveryService"),
    "ReleaseFocusCommand": ("yoyopod.core.focus", "ReleaseFocusCommand"),
    "RequestFocusCommand": ("yoyopod.core.focus", "RequestFocusCommand"),
    "RequestRecoveryCommand": ("yoyopod.core.recovery", "RequestRecoveryCommand"),
    "RuntimeBootService": ("yoyopod.core.bootstrap", "RuntimeBootService"),
    "RuntimeLoopService": ("yoyopod.core.loop", "RuntimeLoopService"),
    "ShutdownLifecycleService": ("yoyopod.core.shutdown", "ShutdownLifecycleService"),
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
    "UserActivityEvent": ("yoyopod.core.events", "UserActivityEvent"),
    "VoipRuntimeState": ("yoyopod.core.runtime_state", "VoipRuntimeState"),
    "VoiceInteractionState": ("yoyopod.core.runtime_state", "VoiceInteractionState"),
    "VoiceState": ("yoyopod.core.runtime_state", "VoiceState"),
    "YoyoPodApp": ("yoyopod.core.application", "YoyoPodApp"),
    "build_logging_runtime_config": ("yoyopod.core.logging", "build_logging_runtime_config"),
    "format_device_label": ("yoyopod.core.hardware", "format_device_label"),
    "get_subsystem_logger": ("yoyopod.core.logging", "get_subsystem_logger"),
    "init_logger": ("yoyopod.core.logging", "init_logger"),
    "log_shutdown": ("yoyopod.core.logging", "log_shutdown"),
    "log_startup": ("yoyopod.core.logging", "log_startup"),
    "remove_pid_file": ("yoyopod.core.logging", "remove_pid_file"),
    "write_pid_file": ("yoyopod.core.logging", "write_pid_file"),
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
