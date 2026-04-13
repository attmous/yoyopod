"""Unit tests for network backend, PPP process, and manager."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from yoyopy.network.ppp import PppProcess


def test_ppp_spawn_constructs_correct_command():
    """PppProcess.spawn should invoke pppd with the correct arguments."""
    with patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        ppp = PppProcess(serial_port="/dev/ttyUSB3", apn="internet")
        assert ppp.spawn() is True

        args = mock_popen.call_args[0][0]
        assert "pppd" in args[0]
        assert "/dev/ttyUSB3" in args
        assert mock_proc.pid == 12345


def test_ppp_kill_terminates_process():
    """PppProcess.kill should terminate then wait."""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    ppp = PppProcess(serial_port="/dev/ttyUSB3", apn="internet")
    ppp._process = mock_proc
    ppp.kill()

    mock_proc.terminate.assert_called_once()
    assert ppp._process is None


def test_ppp_is_alive_when_running():
    """is_alive should return True when pppd is running."""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    ppp = PppProcess(serial_port="/dev/ttyUSB3", apn="internet")
    ppp._process = mock_proc
    assert ppp.is_alive() is True


def test_ppp_is_alive_when_dead():
    """is_alive should return False when no process."""
    ppp = PppProcess(serial_port="/dev/ttyUSB3", apn="internet")
    assert ppp.is_alive() is False


# ---------------------------------------------------------------------------
# Backend tests
# ---------------------------------------------------------------------------

from yoyopy.network.backend import NetworkBackend, Sim7600Backend
from yoyopy.network.models import ModemPhase, ModemState, SignalInfo


class FakeAtCommands:
    """AT command double for backend tests."""

    def __init__(self) -> None:
        self.sim_ready = True
        self.registered = True
        self.signal = SignalInfo(csq=20)
        self.carrier = ("T-Mobile", "4G")
        self.gps_enabled = False
        self.calls: list[str] = []

    def ping(self) -> bool:
        self.calls.append("ping")
        return True

    def echo_off(self) -> None:
        self.calls.append("echo_off")

    def check_sim(self) -> bool:
        self.calls.append("check_sim")
        return self.sim_ready

    def get_signal_quality(self) -> SignalInfo:
        self.calls.append("get_signal_quality")
        return self.signal

    def get_carrier(self) -> tuple[str, str]:
        self.calls.append("get_carrier")
        return self.carrier

    def get_registration(self) -> bool:
        self.calls.append("get_registration")
        return self.registered

    def configure_pdp(self, apn: str) -> None:
        self.calls.append(f"configure_pdp:{apn}")

    def enable_gps(self) -> bool:
        self.calls.append("enable_gps")
        self.gps_enabled = True
        return True

    def hangup(self) -> None:
        self.calls.append("hangup")

    def radio_off(self) -> None:
        self.calls.append("radio_off")


class FakePpp:
    """PPP process double."""

    def __init__(self) -> None:
        self.alive = False
        self.calls: list[str] = []

    def spawn(self) -> bool:
        self.calls.append("spawn")
        self.alive = True
        return True

    def is_alive(self) -> bool:
        return self.alive

    def kill(self) -> None:
        self.calls.append("kill")
        self.alive = False


def test_backend_probe_success():
    """probe should return True when modem responds to AT."""
    at = FakeAtCommands()
    ppp = FakePpp()
    backend = Sim7600Backend.__new__(Sim7600Backend)
    backend._at = at
    backend._ppp = ppp
    backend._gps = None
    backend._state = ModemState()
    backend._config = None

    assert backend.probe() is True
    assert "ping" in at.calls


def test_backend_init_modem_sequence():
    """init_modem should run the full startup sequence."""
    at = FakeAtCommands()
    ppp = FakePpp()
    backend = Sim7600Backend.__new__(Sim7600Backend)
    backend._at = at
    backend._ppp = ppp
    backend._gps = None
    backend._state = ModemState()

    class FakeConfig:
        gps_enabled = True
        apn = "internet"

    backend._config = FakeConfig()
    backend.init_modem()

    assert backend._state.phase == ModemPhase.REGISTERED
    assert backend._state.sim_ready is True
    assert backend._state.carrier == "T-Mobile"
    assert backend._state.network_type == "4G"
    assert backend._state.signal.bars == 3
    assert "enable_gps" in at.calls


def test_backend_start_ppp():
    """start_ppp should transition to ONLINE phase."""
    at = FakeAtCommands()
    ppp = FakePpp()
    backend = Sim7600Backend.__new__(Sim7600Backend)
    backend._at = at
    backend._ppp = ppp
    backend._gps = None
    backend._state = ModemState(phase=ModemPhase.REGISTERED)

    class FakeConfig:
        apn = "internet"

    backend._config = FakeConfig()
    backend.start_ppp()

    assert backend._state.phase == ModemPhase.ONLINE
    assert "spawn" in ppp.calls
    assert "configure_pdp:internet" in at.calls
