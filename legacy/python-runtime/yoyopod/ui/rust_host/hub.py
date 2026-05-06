"""Hub view-model helpers for the Rust UI host."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

HubRenderer = Literal["auto", "lvgl", "framebuffer"]


@dataclass(frozen=True, slots=True)
class RustHubSnapshot:
    """Payload shaped like the current Python LVGL Hub sync contract."""

    icon_key: str
    title: str
    subtitle: str
    footer: str
    time_text: str
    accent: int
    selected_index: int
    total_cards: int
    voip_state: int
    battery_percent: int
    charging: bool
    power_available: bool

    @classmethod
    def static(cls) -> RustHubSnapshot:
        return cls(
            icon_key="listen",
            title="Listen",
            subtitle="",
            footer="Tap = Next | 2x Tap = Open",
            time_text="12:00",
            accent=0x00FF88,
            selected_index=0,
            total_cards=4,
            voip_state=1,
            battery_percent=100,
            charging=False,
            power_available=True,
        )

    def to_payload(self, *, renderer: HubRenderer = "auto") -> dict[str, object]:
        return {
            "renderer": renderer,
            "icon_key": self.icon_key,
            "title": self.title,
            "subtitle": self.subtitle,
            "footer": self.footer,
            "time_text": self.time_text,
            "accent": self.accent,
            "selected_index": self.selected_index,
            "total_cards": self.total_cards,
            "voip_state": self.voip_state,
            "battery_percent": self.battery_percent,
            "charging": self.charging,
            "power_available": self.power_available,
        }
