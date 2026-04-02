"""Tests for profile-aware input-manager creation."""

from __future__ import annotations

from yoyopy.ui.input import InteractionProfile, get_input_manager
from yoyopy.ui.input.adapters.ptt_button import PTTInputAdapter


class WhisplayDisplayAdapter:
    """Minimal Whisplay display-adapter double for factory tests."""

    def __init__(self) -> None:
        self.device = None


def test_whisplay_factory_applies_one_button_profile_and_custom_timings() -> None:
    """Whisplay factory wiring should pass typed timing settings into the adapter."""
    manager = get_input_manager(
        WhisplayDisplayAdapter(),
        config={
            "input": {
                "ptt_navigation": True,
                "whisplay_debounce_ms": 80,
                "whisplay_double_tap_ms": 240,
                "whisplay_long_hold_ms": 950,
            }
        },
        simulate=True,
    )

    assert manager is not None
    assert manager.interaction_profile == InteractionProfile.ONE_BUTTON
    assert len(manager.adapters) == 1

    adapter = manager.adapters[0]
    assert isinstance(adapter, PTTInputAdapter)
    assert adapter.enable_navigation is True
    assert adapter.debounce_time == 0.08
    assert adapter.double_click_time == 0.24
    assert adapter.long_press_time == 0.95
