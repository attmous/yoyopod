"""Tests for the Rust-only network domain cutover."""

from __future__ import annotations

import importlib

import pytest

import yoyopod.integrations.network as network_module


def test_network_package_only_exports_rust_facade() -> None:
    """The supported Python surface should collapse to the Rust worker facade only."""

    assert hasattr(network_module, "RustNetworkFacade")

    for legacy_name in (
        "DisablePppCommand",
        "EnablePppCommand",
        "GpsCoordinate",
        "ModemPhase",
        "ModemState",
        "NetworkEventHandler",
        "NetworkManager",
        "NetworkModemReadyEvent",
        "NetworkPppDownEvent",
        "NetworkPppUpEvent",
        "NetworkRegisteredEvent",
        "NetworkSignalUpdateEvent",
        "RefreshSignalCommand",
        "SetApnCommand",
        "SignalInfo",
    ):
        with pytest.raises(AttributeError):
            getattr(network_module, legacy_name)


def test_legacy_python_network_and_gps_modules_are_removed() -> None:
    """No Python SIM7600/PPP/GPS runtime modules should remain importable."""

    for module_name in (
        "yoyopod.backends.location",
        "yoyopod.backends.location.gps",
        "yoyopod.backends.network",
        "yoyopod.backends.network.at_commands",
        "yoyopod.backends.network.modem",
        "yoyopod.backends.network.ppp",
        "yoyopod.backends.network.transport",
        "yoyopod.integrations.location",
        "yoyopod.integrations.location.commands",
        "yoyopod.integrations.location.events",
        "yoyopod.integrations.location.handlers",
        "yoyopod.integrations.network.commands",
        "yoyopod.integrations.network.events",
        "yoyopod.integrations.network.handlers",
        "yoyopod.integrations.network.manager",
        "yoyopod.integrations.network.models",
        "yoyopod.integrations.network.poller",
    ):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(module_name)
