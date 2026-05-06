"""
Display adapter implementations.

Each adapter provides a hardware-specific implementation of the DisplayHAL interface.

Adapters are imported lazily to avoid side effects (GPIO claims, driver loading)
when the adapter is not selected. Use the display factory to create adapters.
"""

__all__ = [
    "PimoroniDisplayAdapter",
    "SimulationDisplayAdapter",
    "WhisplayDisplayAdapter",
]


def __getattr__(name: str):
    if name == "PimoroniDisplayAdapter":
        from yoyopod_cli.pi.support.display.adapters.pimoroni import PimoroniDisplayAdapter

        return PimoroniDisplayAdapter
    if name == "SimulationDisplayAdapter":
        from yoyopod_cli.pi.support.display.adapters.simulation import SimulationDisplayAdapter

        return SimulationDisplayAdapter
    if name == "WhisplayDisplayAdapter":
        from yoyopod_cli.pi.support.display.adapters.whisplay import WhisplayDisplayAdapter

        return WhisplayDisplayAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
