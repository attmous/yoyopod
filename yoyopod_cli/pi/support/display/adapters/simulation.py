"""LVGL-backed simulation adapter preserving the historical simulation surface."""

from __future__ import annotations

from yoyopod_cli.pi.support.display.adapters.whisplay import WhisplayDisplayAdapter


class SimulationDisplayAdapter(WhisplayDisplayAdapter):
    """Browser-preview simulation adapter using the shared Whisplay LVGL path."""

    DISPLAY_TYPE = "simulation"
    SIMULATED_HARDWARE = "whisplay"

    def __init__(self, *, lvgl_buffer_lines: int = 40) -> None:
        super().__init__(
            simulate=True,
            renderer="lvgl",
            lvgl_buffer_lines=lvgl_buffer_lines,
            enforce_production_contract=False,
        )
        self.SIMULATED_HARDWARE = "whisplay"
