"""Navigation soak plan: error type, step/report dataclasses, plan builder."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from yoyopod_cli.pi.support.input import InputAction


class NavigationSoakError(RuntimeError):
    """Raised when the target navigation soak cannot complete successfully."""


@dataclass(frozen=True, slots=True)
class NavigationSoakStep:
    """One deterministic transition or simulated click in the soak plan."""

    kind: str
    description: str
    target: str | None = None
    action: InputAction | None = None
    wait_for_route: str | None = None
    expect_track_loaded: bool = False
    reset_selection_after_wait: bool = False


@dataclass(frozen=True, slots=True)
class NavigationSoakReport:
    """Compact result summary for one navigation and idle stability pass."""

    cycles: int
    actions: int
    transitions: int
    final_route: str
    sleep_details: str
    music_enabled: bool
    music_state: str
    track_name: str | None
    music_dir: Path | None

    def summary(self) -> str:
        """Return a stable human-readable summary string."""

        details = [
            "backend=lvgl",
            f"cycles={self.cycles}",
            f"actions={self.actions}",
            f"transitions={self.transitions}",
            f"final_screen={self.final_route}",
            self.sleep_details,
        ]
        if self.music_enabled:
            details.append(f"music_state={self.music_state}")
            if self.track_name:
                details.append(f"track={self.track_name}")
            if self.music_dir is not None:
                details.append(f"music_dir={self.music_dir}")
        return ", ".join(details)


def build_navigation_soak_plan(*, with_music: bool) -> tuple[NavigationSoakStep, ...]:
    """Build the deterministic screen-and-click soak plan for the target app."""

    steps: list[NavigationSoakStep] = [
        NavigationSoakStep("replace", "Reset to the root hub", target="hub"),
        NavigationSoakStep(
            "action",
            "Open Listen from the hub",
            action=InputAction.SELECT,
            wait_for_route="listen",
            reset_selection_after_wait=True,
        ),
        NavigationSoakStep(
            "action",
            "Open Playlists from Listen",
            action=InputAction.SELECT,
            wait_for_route="playlists",
            reset_selection_after_wait=True,
        ),
    ]

    if with_music:
        steps.extend(
            [
                NavigationSoakStep(
                    "action",
                    "Load the first playlist into Now Playing",
                    action=InputAction.SELECT,
                    wait_for_route="now_playing",
                    expect_track_loaded=True,
                ),
                NavigationSoakStep(
                    "action",
                    "Pause playback from Now Playing",
                    action=InputAction.PLAY_PAUSE,
                ),
                NavigationSoakStep(
                    "action",
                    "Resume playback from Now Playing",
                    action=InputAction.PLAY_PAUSE,
                ),
                NavigationSoakStep(
                    "action",
                    "Skip to the next track",
                    action=InputAction.NEXT_TRACK,
                    expect_track_loaded=True,
                ),
                NavigationSoakStep(
                    "action",
                    "Return to Playlists",
                    action=InputAction.BACK,
                    wait_for_route="playlists",
                    reset_selection_after_wait=True,
                ),
            ]
        )

    steps.extend(
        [
            NavigationSoakStep(
                "action",
                "Return to Listen",
                action=InputAction.BACK,
                wait_for_route="listen",
                reset_selection_after_wait=True,
            ),
            NavigationSoakStep(
                "action",
                "Move to the Recent row",
                action=InputAction.ADVANCE,
            ),
            NavigationSoakStep(
                "action",
                "Open Recent tracks",
                action=InputAction.SELECT,
                wait_for_route="recent_tracks",
            ),
            NavigationSoakStep(
                "action",
                "Return to Listen from Recent",
                action=InputAction.BACK,
                wait_for_route="listen",
            ),
            NavigationSoakStep(
                "action",
                "Return to the hub",
                action=InputAction.BACK,
                wait_for_route="hub",
                reset_selection_after_wait=True,
            ),
            NavigationSoakStep(
                "action",
                "Advance to Talk",
                action=InputAction.ADVANCE,
            ),
            NavigationSoakStep(
                "action",
                "Open Talk",
                action=InputAction.SELECT,
                wait_for_route="call",
            ),
            NavigationSoakStep(
                "action",
                "Return to the hub from Talk",
                action=InputAction.BACK,
                wait_for_route="hub",
            ),
            NavigationSoakStep(
                "action",
                "Advance to Ask",
                action=InputAction.ADVANCE,
            ),
            NavigationSoakStep(
                "action",
                "Open Ask",
                action=InputAction.SELECT,
                wait_for_route="ask",
            ),
            NavigationSoakStep(
                "action",
                "Return to the hub from Ask",
                action=InputAction.BACK,
                wait_for_route="hub",
            ),
            NavigationSoakStep(
                "action",
                "Advance to Setup",
                action=InputAction.ADVANCE,
            ),
            NavigationSoakStep(
                "action",
                "Open Setup",
                action=InputAction.SELECT,
                wait_for_route="power",
            ),
            NavigationSoakStep(
                "action",
                "Return to the hub from Setup",
                action=InputAction.BACK,
                wait_for_route="hub",
            ),
        ]
    )
    return tuple(steps)
