"""Minimal GPS endpoint for on-demand location queries.

Run on the Pi:
    uvicorn demos.demo_gps_server:app --host 0.0.0.0 --port 8080

Query from the network:
    curl http://rpi-zero:8080/location
    curl http://rpi-zero:8080/health
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure the project root is on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from yoyopy.config import ConfigManager
from yoyopy.network import NetworkManager
from yoyopy.network.backend import Sim7600Backend

app = FastAPI(title="YoyoPod GPS Demo")

_manager: NetworkManager | None = None
_backend: Sim7600Backend | None = None


def _get_backend() -> Sim7600Backend:
    global _manager, _backend
    if _backend is None:
        config_manager = ConfigManager(config_dir="config")
        _manager = NetworkManager.from_config_manager(config_manager)
        _backend = Sim7600Backend(_manager.config)
        _backend.open()
        _backend.init_modem()
    return _backend


@app.get("/location")
def get_location() -> JSONResponse:
    """Query GPS coordinates from the SIM7600 modem."""
    try:
        backend = _get_backend()
        coord = backend.query_gps()
        if coord is None:
            return JSONResponse(
                status_code=404,
                content={"error": "No GPS fix available"},
            )
        return JSONResponse(content={
            "lat": coord.lat,
            "lng": coord.lng,
            "altitude": coord.altitude,
            "speed": coord.speed,
            "timestamp": coord.timestamp.isoformat() if coord.timestamp else None,
        })
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": str(exc)},
        )


@app.get("/health")
def get_health() -> JSONResponse:
    """Return modem health status."""
    try:
        backend = _get_backend()
        state = backend.get_state()
        return JSONResponse(content={
            "phase": state.phase.value,
            "sim_ready": state.sim_ready,
            "carrier": state.carrier,
            "network_type": state.network_type,
            "signal_bars": state.signal.bars if state.signal else None,
            "signal_csq": state.signal.csq if state.signal else None,
            "error": state.error or None,
        })
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": str(exc)},
        )
