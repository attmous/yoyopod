"""Runtime services that keep ``YoyoPodApp`` thin and compositional."""

from yoyopy.runtime.loop import RuntimeLoopService
from yoyopy.runtime.models import PendingShutdown, PowerAlert, RecoveryState
from yoyopy.runtime.recovery import RecoverySupervisor
from yoyopy.runtime.screen_power import ScreenPowerService
from yoyopy.runtime.shutdown import ShutdownLifecycleService
from yoyopy.runtime.voice import (
    VoiceCommandExecutor,
    VoiceCommandOutcome,
    VoiceRuntimeCoordinator,
    VoiceSettingsResolver,
)

__all__ = [
    "PendingShutdown",
    "PowerAlert",
    "RecoveryState",
    "RecoverySupervisor",
    "RuntimeBootService",
    "RuntimeLoopService",
    "ScreenPowerService",
    "ShutdownLifecycleService",
    "VoiceCommandExecutor",
    "VoiceCommandOutcome",
    "VoiceRuntimeCoordinator",
    "VoiceSettingsResolver",
]


def __getattr__(name: str):
    """Load heavyweight runtime services lazily to avoid package import cycles."""

    if name == "RuntimeBootService":
        from yoyopy.runtime.boot import RuntimeBootService

        return RuntimeBootService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
