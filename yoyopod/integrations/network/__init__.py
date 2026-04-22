"""Network integration scaffold for the Phase A spine rewrite.

GPS belongs to `yoyopod.integrations.location`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from yoyopod.integrations.network.commands import (
    DisablePppCommand,
    EnablePppCommand,
    RefreshSignalCommand,
    SetApnCommand,
)
from yoyopod.integrations.network.handlers import (
    apply_modem_status_to_state,
    apply_ppp_status_to_state,
    apply_signal_to_state,
)
from yoyopod.integrations.network.poller import NetworkPoller

if TYPE_CHECKING:
    from yoyopod.backends.network import ModemBackend, PPPBackend
    from yoyopod.integrations.network.manager import NetworkManager
    from yoyopod.integrations.network.models import (
        GpsCoordinate,
        ModemPhase,
        ModemState,
        SignalInfo,
    )


_PUBLIC_EXPORTS = {
    "GpsCoordinate": ("yoyopod.integrations.network.models", "GpsCoordinate"),
    "ModemPhase": ("yoyopod.integrations.network.models", "ModemPhase"),
    "ModemState": ("yoyopod.integrations.network.models", "ModemState"),
    "NetworkManager": ("yoyopod.integrations.network.manager", "NetworkManager"),
    "NetworkEventHandler": ("yoyopod.integrations.network.handlers", "NetworkEventHandler"),
    "NetworkModemReadyEvent": ("yoyopod.integrations.network.events", "NetworkModemReadyEvent"),
    "NetworkPppDownEvent": ("yoyopod.integrations.network.events", "NetworkPppDownEvent"),
    "NetworkPppUpEvent": ("yoyopod.integrations.network.events", "NetworkPppUpEvent"),
    "NetworkRegisteredEvent": ("yoyopod.integrations.network.events", "NetworkRegisteredEvent"),
    "NetworkSignalUpdateEvent": (
        "yoyopod.integrations.network.events",
        "NetworkSignalUpdateEvent",
    ),
    "SignalInfo": ("yoyopod.integrations.network.models", "SignalInfo"),
}


def __getattr__(name: str) -> Any:
    """Load canonical public network exports lazily to avoid backend import cycles."""

    try:
        module_name, attribute = _PUBLIC_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = __import__(module_name, fromlist=[attribute])
    return getattr(module, attribute)


@dataclass(slots=True)
class NetworkIntegration:
    """Runtime handles owned by the scaffold network integration."""

    backend: object
    poller: NetworkPoller


def setup(
    app: Any,
    *,
    backend: object | None = None,
    poll_interval_seconds: float | None = None,
) -> NetworkIntegration:
    """Register scaffold network services and start modem polling."""

    actual_backend = backend or _build_backend(_resolve_network_config(app.config))
    actual_interval = (
        15.0
        if poll_interval_seconds is None
        else max(0.1, float(poll_interval_seconds))
    )
    integration = NetworkIntegration(
        backend=actual_backend,
        poller=NetworkPoller(
            app=app,
            backend=actual_backend,
            poll_interval_seconds=actual_interval,
        ),
    )
    app.integrations["network"] = integration
    apply_modem_status_to_state(
        app,
        _StatusSnapshot(registered=False, carrier="", network_type=""),
    )
    apply_signal_to_state(app, csq=None, bars=None)
    apply_ppp_status_to_state(app, up=False, reason="idle")
    app.services.register(
        "network",
        "enable_ppp",
        lambda data: _handle_enable_ppp(app, actual_backend, data),
    )
    app.services.register(
        "network",
        "disable_ppp",
        lambda data: _handle_disable_ppp(app, actual_backend, data),
    )
    app.services.register(
        "network",
        "refresh_signal",
        lambda data: _handle_refresh_signal(app, actual_backend, data),
    )
    app.services.register(
        "network",
        "set_apn",
        lambda data: _handle_set_apn(actual_backend, data),
    )
    integration.poller.start()
    return integration


def teardown(app: Any) -> None:
    """Stop the network poller and close the scaffold network backend."""

    integration = app.integrations.pop("network", None)
    if integration is None:
        return
    integration.poller.stop()
    close = getattr(integration.backend, "close", None)
    if callable(close):
        close()


def _handle_enable_ppp(app: Any, backend: object, command: EnablePppCommand) -> bool:
    if not isinstance(command, EnablePppCommand):
        raise TypeError("network.enable_ppp expects EnablePppCommand")
    enabled = bool(backend.enable_ppp())
    apply_ppp_status_to_state(app, up=enabled, reason="enabled" if enabled else "failed")
    return enabled


def _handle_disable_ppp(app: Any, backend: object, command: DisablePppCommand) -> bool:
    if not isinstance(command, DisablePppCommand):
        raise TypeError("network.disable_ppp expects DisablePppCommand")
    backend.disable_ppp()
    apply_ppp_status_to_state(app, up=False, reason="disabled")
    return True


def _handle_refresh_signal(app: Any, backend: object, command: RefreshSignalCommand) -> object | None:
    if not isinstance(command, RefreshSignalCommand):
        raise TypeError("network.refresh_signal expects RefreshSignalCommand")
    signal = backend.get_signal()
    apply_signal_to_state(
        app,
        csq=None if signal is None else getattr(signal, "csq", None),
        bars=None if signal is None else getattr(signal, "bars", None),
    )
    return signal


def _handle_set_apn(backend: object, command: SetApnCommand) -> None:
    if not isinstance(command, SetApnCommand):
        raise TypeError("network.set_apn expects SetApnCommand")
    backend.set_apn(
        apn=command.apn,
        username=command.username,
        password=command.password,
    )


def _resolve_network_config(config: object | None) -> object:
    if config is None:
        raise ValueError("network setup requires app.config or an explicit backend")

    get_network_settings = getattr(config, "get_network_settings", None)
    if callable(get_network_settings):
        return get_network_settings()

    network = getattr(config, "network", None)
    if network is None:
        raise ValueError("network setup requires config.network")
    return network


class _ModemPppAdapter:
    """Combine one modem adapter and PPP adapter behind scaffold service methods."""

    def __init__(self, *, config: object, modem: ModemBackend, ppp: PPPBackend) -> None:
        self._config = config
        self._modem = modem
        self._ppp = ppp
        self._apn = str(getattr(config, "apn", "") or "")
        self._username = ""
        self._password = ""

    def get_status(self) -> object:
        return self._modem.get_status()

    def get_signal(self) -> object | None:
        return self._modem.get_signal()

    def enable_ppp(self) -> bool:
        if self._apn:
            self._modem.set_apn(apn=self._apn, username=self._username, password=self._password)
        return self._ppp.bring_up()

    def disable_ppp(self) -> None:
        self._ppp.tear_down()

    def set_apn(self, *, apn: str, username: str = "", password: str = "") -> None:
        self._apn = apn
        self._username = username
        self._password = password
        if apn:
            self._modem.set_apn(apn=apn, username=username, password=password)

    def close(self) -> None:
        try:
            self._ppp.tear_down()
        finally:
            self._modem.close()


@dataclass(frozen=True, slots=True)
class _StatusSnapshot:
    registered: bool
    carrier: str
    network_type: str


def _build_backend(config: object) -> _ModemPppAdapter:
    from yoyopod.backends.network import ModemBackend, PPPBackend

    modem = ModemBackend(config)
    ppp = PPPBackend(config)
    return _ModemPppAdapter(config=config, modem=modem, ppp=ppp)


__all__ = [
    "DisablePppCommand",
    "EnablePppCommand",
    "GpsCoordinate",
    "ModemPhase",
    "ModemState",
    "NetworkEventHandler",
    "NetworkIntegration",
    "NetworkManager",
    "NetworkModemReadyEvent",
    "NetworkPppDownEvent",
    "NetworkPppUpEvent",
    "NetworkRegisteredEvent",
    "NetworkSignalUpdateEvent",
    "RefreshSignalCommand",
    "SetApnCommand",
    "SignalInfo",
    "setup",
    "teardown",
]
