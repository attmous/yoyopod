"""Tests for the scaffold service registry."""

from __future__ import annotations

import threading

import pytest

from yoyopod.core import Bus, LogBuffer, Services


def test_services_register_and_call_records_log_entries() -> None:
    bus = Bus()
    log_buffer: LogBuffer[dict[str, object]] = LogBuffer(maxlen=8)
    services = Services(bus, diagnostics_log=log_buffer)
    services.register("music", "pause", lambda data: {"result": data})

    result = services.call("music", "pause", {"reason": "call"})

    assert result == {"result": {"reason": "call"}}
    assert log_buffer.snapshot() == [
        {
            "kind": "command",
            "domain": "music",
            "service": "pause",
            "data": {"reason": "call"},
        }
    ]


def test_services_call_requires_main_thread() -> None:
    bus = Bus()
    services = Services(bus)
    services.register("screen", "wake", lambda data: None)
    errors: list[str] = []

    worker = threading.Thread(target=lambda: _call_off_main(services, errors))
    worker.start()
    worker.join()

    assert errors == ["Services.call() must run on the main thread"]


def test_services_call_raises_for_unknown_service() -> None:
    bus = Bus()
    services = Services(bus)

    with pytest.raises(KeyError, match="Unknown service: call.answer"):
        services.call("call", "answer")


def test_services_duplicate_registration_raises() -> None:
    bus = Bus()
    services = Services(bus)
    services.register("call", "answer", lambda data: None)

    with pytest.raises(ValueError, match="Service already registered: call.answer"):
        services.register("call", "answer", lambda data: None)


def _call_off_main(services: Services, errors: list[str]) -> None:
    try:
        services.call("screen", "wake")
    except RuntimeError as exc:
        errors.append(str(exc))
