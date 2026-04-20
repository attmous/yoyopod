# 4G Cellular Connectivity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a cellular connectivity layer to YoyoPod using the Waveshare SIM7600G-H 4G HAT B over UART, providing PPP internet for VoIP, modem telemetry for the UI, and on-demand GPS.

**Architecture:** A new `src/yoyopod/network/` package follows the power module's Protocol + Backend + Manager pattern. A `SerialTransport` handles UART communication, an AT command layer parses modem responses into typed dataclasses, a `PppProcess` (modeled on `MpvProcess`) manages the `pppd` subprocess, and a `NetworkManager` facade integrates with the EventBus and AppContext. The modem serial port is shared — telemetry snapshots are taken before PPP starts, GPS queries briefly tear down PPP.

**Tech Stack:** Python 3.12+, pyserial, pppd (system), typer (CLI), FastAPI (demo server), pytest

---

## File Structure

### New Files

| File | Responsibility |
|---|---|
| `src/yoyopod/network/__init__.py` | Public API exports |
| `src/yoyopod/network/models.py` | `ModemState`, `SignalInfo`, `GpsCoordinate`, `NetworkConfig` dataclasses |
| `src/yoyopod/network/transport.py` | `SerialTransport` — thread-safe pyserial UART wrapper |
| `src/yoyopod/network/at_commands.py` | Typed AT command builder/parser |
| `src/yoyopod/network/ppp.py` | `PppProcess` — pppd subprocess lifecycle (MpvProcess pattern) |
| `src/yoyopod/network/gps.py` | `GpsReader` — GPS enable/query via AT commands |
| `src/yoyopod/network/backend.py` | `NetworkBackend` protocol + `Sim7600Backend` implementation |
| `src/yoyopod/network/manager.py` | `NetworkManager` facade (PowerManager pattern) |
| `src/yoyopod/cli/pi/network.py` | `yoyopod pi network` CLI commands |
| `demos/demo_gps_server.py` | Minimal FastAPI GPS endpoint |
| `tests/test_network_models.py` | Model and config tests |
| `tests/test_network_transport.py` | Transport and AT command tests |
| `tests/test_network_backend.py` | Backend lifecycle and PPP tests |
| `tests/test_network_manager.py` | Manager facade and EventBus integration tests |

### Modified Files

| File | Change |
|---|---|
| `src/yoyopod/config/models.py` | Add `AppNetworkConfig` dataclass, wire into `YoyoPodConfig` |
| `src/yoyopod/events.py` | Add network event dataclasses |
| `src/yoyopod/app_context.py` | Add `update_network_status()` method |
| `src/yoyopod/app.py` | Wire `NetworkManager` into app bootstrap and main loop |
| `src/yoyopod/cli/__init__.py` | Register `network` subcommand group |
| `config/yoyopod_config.yaml` | Add `network:` section |
| `pyproject.toml` | Add `pyserial` dependency |

---

## Task 1: Data Models and Config

**Files:**
- Create: `src/yoyopod/network/__init__.py`
- Create: `src/yoyopod/network/models.py`
- Modify: `src/yoyopod/config/models.py:337-349` (YoyoPodConfig)
- Modify: `config/yoyopod_config.yaml`
- Modify: `pyproject.toml`
- Test: `tests/test_network_models.py`

- [ ] **Step 1: Write failing test for network models**

```python
# tests/test_network_models.py
"""Unit tests for network data models and config."""

from __future__ import annotations

from yoyopod.network.models import (
    GpsCoordinate,
    ModemState,
    ModemPhase,
    SignalInfo,
)


def test_modem_state_defaults():
    """ModemState should have sensible defaults for an uninitialized modem."""
    state = ModemState()
    assert state.phase == ModemPhase.OFF
    assert state.signal is None
    assert state.carrier == ""
    assert state.network_type == ""
    assert state.gps is None


def test_signal_info_bars_mapping():
    """SignalInfo.bars should map raw CSQ 0-31 to 0-4 bars."""
    assert SignalInfo(csq=0).bars == 0
    assert SignalInfo(csq=5).bars == 1
    assert SignalInfo(csq=12).bars == 2
    assert SignalInfo(csq=20).bars == 3
    assert SignalInfo(csq=28).bars == 4
    assert SignalInfo(csq=99).bars == 0  # 99 = not detectable


def test_gps_coordinate_fields():
    """GpsCoordinate should store lat/lng/altitude/speed."""
    coord = GpsCoordinate(lat=48.8566, lng=2.3522, altitude=35.0, speed=0.0)
    assert coord.lat == 48.8566
    assert coord.lng == 2.3522
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_network_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yoyopod.network'`

- [ ] **Step 3: Create network package with models**

```python
# src/yoyopod/network/__init__.py
"""4G cellular connectivity for YoyoPod."""
```

```python
# src/yoyopod/network/models.py
"""Typed data models for the SIM7600G-H modem backend."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ModemPhase(str, Enum):
    """Modem lifecycle phases."""

    OFF = "off"
    PROBING = "probing"
    READY = "ready"
    REGISTERING = "registering"
    REGISTERED = "registered"
    PPP_STARTING = "ppp_starting"
    ONLINE = "online"
    PPP_STOPPING = "ppp_stopping"


@dataclass(frozen=True, slots=True)
class SignalInfo:
    """Parsed AT+CSQ response."""

    csq: int = 0

    @property
    def bars(self) -> int:
        """Map raw CSQ value (0-31, 99) to 0-4 signal bars."""
        if self.csq == 99 or self.csq < 1:
            return 0
        if self.csq < 10:
            return 1
        if self.csq < 15:
            return 2
        if self.csq < 25:
            return 3
        return 4


@dataclass(frozen=True, slots=True)
class GpsCoordinate:
    """Parsed AT+CGPSINFO response."""

    lat: float
    lng: float
    altitude: float = 0.0
    speed: float = 0.0
    timestamp: Optional[datetime] = None


@dataclass(slots=True)
class ModemState:
    """Mutable current modem state snapshot."""

    phase: ModemPhase = ModemPhase.OFF
    signal: Optional[SignalInfo] = None
    carrier: str = ""
    network_type: str = ""
    sim_ready: bool = False
    gps: Optional[GpsCoordinate] = None
    error: str = ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_network_models.py -v`
Expected: all 3 tests PASS

- [ ] **Step 5: Write failing test for NetworkConfig**

Add to `tests/test_network_models.py`:

```python
from yoyopod.config.models import YoyoPodConfig, build_config_model


def test_network_config_defaults():
    """NetworkConfig should be disabled by default with sane defaults."""
    config = build_config_model(YoyoPodConfig, {})
    assert config.network.enabled is False
    assert config.network.serial_port == "/dev/ttyS0"
    assert config.network.baud_rate == 115200
    assert config.network.apn == ""
    assert config.network.gps_enabled is True
    assert config.network.ppp_timeout == 30


def test_network_config_from_yaml_data():
    """NetworkConfig should load from YAML data."""
    data = {"network": {"enabled": True, "apn": "internet", "serial_port": "/dev/ttyAMA0"}}
    config = build_config_model(YoyoPodConfig, data)
    assert config.network.enabled is True
    assert config.network.apn == "internet"
    assert config.network.serial_port == "/dev/ttyAMA0"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/test_network_models.py::test_network_config_defaults -v`
Expected: FAIL with `AttributeError: 'YoyoPodConfig' object has no attribute 'network'`

- [ ] **Step 7: Add AppNetworkConfig to config models**

Add to `src/yoyopod/config/models.py` before `YoyoPodConfig`:

```python
@dataclass(slots=True)
class AppNetworkConfig:
    """4G cellular modem settings."""

    enabled: bool = config_value(default=False, env="YOYOPOD_NETWORK_ENABLED")
    serial_port: str = config_value(default="/dev/ttyS0", env="YOYOPOD_MODEM_PORT")
    baud_rate: int = config_value(default=115200, env="YOYOPOD_MODEM_BAUD")
    apn: str = config_value(default="", env="YOYOPOD_MODEM_APN")
    pin: str | None = config_value(default=None)
    gps_enabled: bool = config_value(default=True, env="YOYOPOD_MODEM_GPS_ENABLED")
    ppp_timeout: int = config_value(default=30, env="YOYOPOD_MODEM_PPP_TIMEOUT")
```

Add `network` field to `YoyoPodConfig`:

```python
network: AppNetworkConfig = config_value(default_factory=AppNetworkConfig)
```

- [ ] **Step 8: Run test to verify it passes**

Run: `uv run pytest tests/test_network_models.py -v`
Expected: all 5 tests PASS

- [ ] **Step 9: Add pyserial dependency and YAML config section**

In `pyproject.toml`, add `pyserial>=3.5` to the dependencies list.

In `config/yoyopod_config.yaml`, add:

```yaml
network:
  enabled: false
  serial_port: /dev/ttyS0
  baud_rate: 115200
  apn: ""
  gps_enabled: true
```

- [ ] **Step 10: Run full test suite**

Run: `uv run pytest -q`
Expected: all existing tests still pass

- [ ] **Step 11: Commit**

```bash
git add src/yoyopod/network/__init__.py src/yoyopod/network/models.py src/yoyopod/config/models.py config/yoyopod_config.yaml pyproject.toml tests/test_network_models.py
git commit -m "feat(network): add modem data models and network config"
```

---

## Task 2: Serial Transport

**Files:**
- Create: `src/yoyopod/network/transport.py`
- Test: `tests/test_network_transport.py`

- [ ] **Step 1: Write failing test for SerialTransport**

```python
# tests/test_network_transport.py
"""Unit tests for the UART serial transport."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

from yoyopod.network.transport import SerialTransport, TransportError


class FakeSerial:
    """Minimal pyserial double."""

    def __init__(self) -> None:
        self.is_open = True
        self._response = b"OK\r\n"
        self.written: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.written.append(data)
        return len(data)

    def read_until(self, expected: bytes = b"\n", size: int | None = None) -> bytes:
        return self._response

    def readline(self) -> bytes:
        return self._response

    def read(self, size: int = 1) -> bytes:
        return self._response[:size]

    def reset_input_buffer(self) -> None:
        pass

    def close(self) -> None:
        self.is_open = False

    @property
    def in_waiting(self) -> int:
        return len(self._response)


def test_send_command_returns_response():
    """send_command should write AT command and return parsed response."""
    fake = FakeSerial()
    transport = SerialTransport.__new__(SerialTransport)
    transport._serial = fake
    transport._lock = threading.Lock()

    result = transport.send_command("AT")
    assert "OK" in result
    assert any(b"AT\r\n" in w for w in fake.written)


def test_send_command_raises_on_closed_port():
    """send_command should raise TransportError when port is closed."""
    transport = SerialTransport.__new__(SerialTransport)
    transport._serial = None
    transport._lock = threading.Lock()

    try:
        transport.send_command("AT")
        assert False, "Expected TransportError"
    except TransportError:
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_network_transport.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yoyopod.network.transport'`

- [ ] **Step 3: Implement SerialTransport**

```python
# src/yoyopod/network/transport.py
"""Thread-safe UART serial transport for AT commands."""

from __future__ import annotations

import threading
import time

from loguru import logger


class TransportError(RuntimeError):
    """Raised when the serial transport cannot complete a command."""


class SerialTransport:
    """Wraps pyserial for AT command communication over UART."""

    def __init__(self, port: str, baud_rate: int = 115200, timeout: float = 2.0) -> None:
        self.port = port
        self.baud_rate = baud_rate
        self.timeout = timeout
        self._serial = None
        self._lock = threading.Lock()

    def open(self) -> None:
        """Open the serial port."""
        import serial

        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baud_rate,
                timeout=self.timeout,
            )
            logger.info("Serial port opened: {} @ {}", self.port, self.baud_rate)
        except Exception as exc:
            raise TransportError(f"Failed to open {self.port}: {exc}") from exc

    def close(self) -> None:
        """Close the serial port."""
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception as exc:
                logger.warning("Error closing serial port: {}", exc)
            finally:
                self._serial = None

    def send_command(self, command: str, timeout: float | None = None) -> str:
        """Send an AT command and return the full response."""
        with self._lock:
            if self._serial is None:
                raise TransportError("Serial port not open")

            cmd_bytes = (command.strip() + "\r\n").encode("ascii")
            self._serial.reset_input_buffer()
            self._serial.write(cmd_bytes)

            deadline = time.monotonic() + (timeout or self.timeout)
            lines: list[str] = []

            while time.monotonic() < deadline:
                raw = self._serial.readline()
                if not raw:
                    continue
                line = raw.decode("ascii", errors="replace").strip()
                if not line:
                    continue
                lines.append(line)
                if line in ("OK", "ERROR") or line.startswith("+CME ERROR"):
                    break

            response = "\n".join(lines)
            logger.debug("AT {} -> {}", command.strip(), response)
            return response

    @property
    def is_open(self) -> bool:
        """Return True when the serial port is open."""
        return self._serial is not None and self._serial.is_open
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_network_transport.py -v`
Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/yoyopod/network/transport.py tests/test_network_transport.py
git commit -m "feat(network): add UART serial transport"
```

---

## Task 3: AT Command Layer

**Files:**
- Create: `src/yoyopod/network/at_commands.py`
- Modify: `tests/test_network_transport.py`

- [ ] **Step 1: Write failing tests for AT command parsing**

Add to `tests/test_network_transport.py`:

```python
from yoyopod.network.at_commands import AtCommandSet
from yoyopod.network.models import SignalInfo


class FakeTransport:
    """Minimal transport double for AT command tests."""

    def __init__(self) -> None:
        self.responses: dict[str, str] = {}
        self.sent: list[str] = []

    def send_command(self, command: str, timeout: float | None = None) -> str:
        self.sent.append(command)
        for prefix, response in self.responses.items():
            if command.strip().startswith(prefix):
                return response
        return "OK"


def test_parse_signal_quality():
    """get_signal_quality should parse AT+CSQ response into SignalInfo."""
    transport = FakeTransport()
    transport.responses["AT+CSQ"] = "+CSQ: 18,0\nOK"
    at = AtCommandSet(transport)
    info = at.get_signal_quality()
    assert info.csq == 18
    assert info.bars == 3


def test_check_sim_ready():
    """check_sim should return True when SIM is READY."""
    transport = FakeTransport()
    transport.responses["AT+CPIN?"] = "+CPIN: READY\nOK"
    at = AtCommandSet(transport)
    assert at.check_sim() is True


def test_check_sim_not_inserted():
    """check_sim should return False when SIM is missing."""
    transport = FakeTransport()
    transport.responses["AT+CPIN?"] = "+CME ERROR: 10"
    at = AtCommandSet(transport)
    assert at.check_sim() is False


def test_get_carrier():
    """get_carrier should parse AT+COPS? response."""
    transport = FakeTransport()
    transport.responses["AT+COPS?"] = '+COPS: 0,0,"T-Mobile",7\nOK'
    at = AtCommandSet(transport)
    carrier, network_type = at.get_carrier()
    assert carrier == "T-Mobile"
    assert network_type == "4G"


def test_get_registration_registered():
    """get_registration should detect home registration."""
    transport = FakeTransport()
    transport.responses["AT+CEREG?"] = "+CEREG: 0,1\nOK"
    at = AtCommandSet(transport)
    assert at.get_registration() is True


def test_get_registration_not_registered():
    """get_registration should detect unregistered state."""
    transport = FakeTransport()
    transport.responses["AT+CEREG?"] = "+CEREG: 0,0\nOK"
    at = AtCommandSet(transport)
    assert at.get_registration() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_network_transport.py::test_parse_signal_quality -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yoyopod.network.at_commands'`

- [ ] **Step 3: Implement AtCommandSet**

```python
# src/yoyopod/network/at_commands.py
"""Typed AT command builder and response parser for SIM7600G-H."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from loguru import logger

from yoyopod.network.models import GpsCoordinate, SignalInfo

if TYPE_CHECKING:
    from yoyopod.network.transport import SerialTransport

# AT+COPS access technology values to human-readable names.
_ACCESS_TECH = {
    "0": "2G",
    "2": "3G",
    "7": "4G",
}


class AtCommandSet:
    """Typed wrapper over SIM7600G-H AT commands."""

    def __init__(self, transport: "SerialTransport") -> None:
        self._transport = transport

    def ping(self) -> bool:
        """Send AT and check for OK."""
        resp = self._transport.send_command("AT")
        return "OK" in resp

    def echo_off(self) -> None:
        """Disable command echo."""
        self._transport.send_command("ATE0")

    def check_sim(self) -> bool:
        """Return True when the SIM is ready."""
        resp = self._transport.send_command("AT+CPIN?")
        return "READY" in resp

    def get_signal_quality(self) -> SignalInfo:
        """Parse AT+CSQ into SignalInfo."""
        resp = self._transport.send_command("AT+CSQ")
        match = re.search(r"\+CSQ:\s*(\d+)", resp)
        csq = int(match.group(1)) if match else 99
        return SignalInfo(csq=csq)

    def get_carrier(self) -> tuple[str, str]:
        """Parse AT+COPS? into (carrier_name, network_type)."""
        resp = self._transport.send_command("AT+COPS?")
        match = re.search(r'\+COPS:\s*\d+,\d+,"([^"]*)",(\d+)', resp)
        if not match:
            return ("", "")
        carrier = match.group(1)
        tech_code = match.group(2)
        network_type = _ACCESS_TECH.get(tech_code, "unknown")
        return (carrier, network_type)

    def get_registration(self) -> bool:
        """Return True when registered on a cellular network."""
        resp = self._transport.send_command("AT+CEREG?")
        match = re.search(r"\+CEREG:\s*\d+,(\d+)", resp)
        if not match:
            return False
        stat = match.group(1)
        return stat in ("1", "5")  # 1=home, 5=roaming

    def configure_pdp(self, apn: str) -> None:
        """Configure PDP context for data."""
        self._transport.send_command(f'AT+CGDCONT=1,"IP","{apn}"')

    def enable_gps(self) -> bool:
        """Enable the GPS engine."""
        resp = self._transport.send_command("AT+CGPS=1")
        return "OK" in resp

    def disable_gps(self) -> None:
        """Disable the GPS engine."""
        self._transport.send_command("AT+CGPS=0")

    def query_gps(self) -> GpsCoordinate | None:
        """Query current GPS fix. Returns None if no fix."""
        resp = self._transport.send_command("AT+CGPSINFO")
        match = re.search(
            r"\+CGPSINFO:\s*"
            r"(\d+\.\d+),([NS]),"
            r"(\d+\.\d+),([EW]),"
            r"(\d+),"           # date
            r"(\d+\.\d+),"     # utc time
            r"(-?\d+\.?\d*),"  # altitude
            r"(\d+\.?\d*),"    # speed
            r"",                # course (ignored)
            resp,
        )
        if not match:
            return None

        lat = float(match.group(1))
        if match.group(2) == "S":
            lat = -lat
        lng = float(match.group(3))
        if match.group(4) == "W":
            lng = -lng
        altitude = float(match.group(7))
        speed = float(match.group(8))

        return GpsCoordinate(lat=lat, lng=lng, altitude=altitude, speed=speed)

    def hangup(self) -> None:
        """Send hangup command."""
        self._transport.send_command("ATH")

    def radio_off(self) -> None:
        """Turn off the radio."""
        self._transport.send_command("AT+CFUN=0")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_network_transport.py -v`
Expected: all 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/yoyopod/network/at_commands.py tests/test_network_transport.py
git commit -m "feat(network): add AT command parser for SIM7600"
```

---

## Task 4: PPP Subprocess Manager

**Files:**
- Create: `src/yoyopod/network/ppp.py`
- Test: `tests/test_network_backend.py`

- [ ] **Step 1: Write failing test for PppProcess**

```python
# tests/test_network_backend.py
"""Unit tests for network backend, PPP process, and manager."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from yoyopod.network.ppp import PppProcess


def test_ppp_spawn_constructs_correct_command():
    """PppProcess.spawn should invoke pppd with the correct arguments."""
    with patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        ppp = PppProcess(serial_port="/dev/ttyS0", apn="internet")
        assert ppp.spawn() is True

        args = mock_popen.call_args[0][0]
        assert "pppd" in args[0]
        assert "/dev/ttyS0" in args
        assert mock_proc.pid == 12345


def test_ppp_kill_terminates_process():
    """PppProcess.kill should terminate then wait."""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    ppp = PppProcess(serial_port="/dev/ttyS0", apn="internet")
    ppp._process = mock_proc
    ppp.kill()

    mock_proc.terminate.assert_called_once()
    assert ppp._process is None


def test_ppp_is_alive_when_running():
    """is_alive should return True when pppd is running."""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    ppp = PppProcess(serial_port="/dev/ttyS0", apn="internet")
    ppp._process = mock_proc
    assert ppp.is_alive() is True


def test_ppp_is_alive_when_dead():
    """is_alive should return False when no process."""
    ppp = PppProcess(serial_port="/dev/ttyS0", apn="internet")
    assert ppp.is_alive() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_network_backend.py::test_ppp_spawn_constructs_correct_command -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yoyopod.network.ppp'`

- [ ] **Step 3: Implement PppProcess**

```python
# src/yoyopod/network/ppp.py
"""pppd subprocess lifecycle manager."""

from __future__ import annotations

import subprocess

from loguru import logger


class PppProcess:
    """Spawn, monitor, and kill a pppd process for cellular data."""

    def __init__(self, serial_port: str, apn: str, baud_rate: int = 115200) -> None:
        self.serial_port = serial_port
        self.apn = apn
        self.baud_rate = baud_rate
        self._process: subprocess.Popen | None = None

    def spawn(self) -> bool:
        """Launch pppd for cellular data."""
        if self._process is not None and self._process.poll() is None:
            logger.warning("pppd already running (pid={})", self._process.pid)
            return True

        cmd = [
            "pppd",
            self.serial_port,
            str(self.baud_rate),
            "nodetach",
            "noauth",
            "defaultroute",
            "usepeerdns",
            "persist",
            "connect",
            f"chat -v '' AT OK 'ATD*99#' CONNECT",
        ]

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            logger.info("pppd spawned (pid={})", self._process.pid)
            return True
        except FileNotFoundError:
            logger.error("pppd binary not found")
            return False
        except Exception as exc:
            logger.error("Failed to spawn pppd: {}", exc)
            return False

    def is_alive(self) -> bool:
        """Return True when the pppd process is running."""
        return self._process is not None and self._process.poll() is None

    def kill(self) -> None:
        """Terminate the pppd process."""
        if self._process is None:
            return

        try:
            self._process.terminate()
            self._process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            logger.warning("pppd did not exit after SIGTERM, sending SIGKILL")
            self._process.kill()
            self._process.wait(timeout=5.0)
        except Exception as exc:
            logger.error("Error killing pppd: {}", exc)
        finally:
            self._process = None

    def respawn(self) -> bool:
        """Kill and restart pppd."""
        self.kill()
        return self.spawn()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_network_backend.py -v`
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/yoyopod/network/ppp.py tests/test_network_backend.py
git commit -m "feat(network): add pppd subprocess manager"
```

---

## Task 5: GPS Reader

**Files:**
- Create: `src/yoyopod/network/gps.py`
- Modify: `tests/test_network_transport.py`

- [ ] **Step 1: Write failing test for GpsReader**

Add to `tests/test_network_transport.py`:

```python
from yoyopod.network.gps import GpsReader


def test_gps_reader_query_with_fix():
    """GpsReader.query should return coordinates when GPS has a fix."""
    transport = FakeTransport()
    transport.responses["AT+CGPSINFO"] = (
        "+CGPSINFO: 4852.4300,N,00221.1300,E,130426,120000.0,35.0,0.5,\nOK"
    )
    reader = GpsReader(transport)
    coord = reader.query()
    assert coord is not None
    assert coord.lat > 0
    assert coord.lng > 0


def test_gps_reader_query_no_fix():
    """GpsReader.query should return None when no GPS fix."""
    transport = FakeTransport()
    transport.responses["AT+CGPSINFO"] = "+CGPSINFO: ,,,,,,,,\nOK"
    reader = GpsReader(transport)
    assert reader.query() is None


def test_gps_reader_enable():
    """GpsReader.enable should send AT+CGPS=1."""
    transport = FakeTransport()
    transport.responses["AT+CGPS=1"] = "OK"
    reader = GpsReader(transport)
    assert reader.enable() is True
    assert "AT+CGPS=1" in transport.sent
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_network_transport.py::test_gps_reader_query_with_fix -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yoyopod.network.gps'`

- [ ] **Step 3: Implement GpsReader**

```python
# src/yoyopod/network/gps.py
"""GPS query and coordinate parsing for SIM7600G-H."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from yoyopod.network.at_commands import AtCommandSet

if TYPE_CHECKING:
    from yoyopod.network.models import GpsCoordinate


class GpsReader:
    """Query GPS position via AT commands on the SIM7600G-H."""

    def __init__(self, transport) -> None:
        self._at = AtCommandSet(transport)

    def enable(self) -> bool:
        """Enable the GPS engine on the modem."""
        return self._at.enable_gps()

    def disable(self) -> None:
        """Disable the GPS engine."""
        self._at.disable_gps()

    def query(self) -> GpsCoordinate | None:
        """Query current GPS fix. Returns None if no fix available."""
        return self._at.query_gps()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_network_transport.py -v`
Expected: all 11 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/yoyopod/network/gps.py tests/test_network_transport.py
git commit -m "feat(network): add GPS reader"
```

---

## Task 6: Network Backend Protocol and Sim7600Backend

**Files:**
- Create: `src/yoyopod/network/backend.py`
- Modify: `tests/test_network_backend.py`

- [ ] **Step 1: Write failing test for Sim7600Backend**

Add to `tests/test_network_backend.py`:

```python
from yoyopod.network.backend import NetworkBackend, Sim7600Backend
from yoyopod.network.models import ModemPhase, ModemState, SignalInfo


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
    assert f"configure_pdp:internet" in at.calls
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_network_backend.py::test_backend_probe_success -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yoyopod.network.backend'`

- [ ] **Step 3: Implement backend**

```python
# src/yoyopod/network/backend.py
"""Network backend protocol and SIM7600G-H implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from loguru import logger

from yoyopod.network.at_commands import AtCommandSet
from yoyopod.network.gps import GpsReader
from yoyopod.network.models import GpsCoordinate, ModemPhase, ModemState
from yoyopod.network.ppp import PppProcess
from yoyopod.network.transport import SerialTransport

if TYPE_CHECKING:
    from yoyopod.config.models import AppNetworkConfig


class NetworkBackend(Protocol):
    """Read-only backend contract for cellular modem integrations."""

    def probe(self) -> bool:
        """Return True when the modem is reachable."""
        ...

    def get_state(self) -> ModemState:
        """Return the current modem state."""
        ...


class Sim7600Backend:
    """SIM7600G-H modem backend over UART."""

    def __init__(self, config: "AppNetworkConfig") -> None:
        self._config = config
        self._transport = SerialTransport(
            port=config.serial_port,
            baud_rate=config.baud_rate,
        )
        self._at = AtCommandSet(self._transport)
        self._ppp = PppProcess(
            serial_port=config.serial_port,
            apn=config.apn,
            baud_rate=config.baud_rate,
        )
        self._gps = GpsReader(self._transport)
        self._state = ModemState()

    def probe(self) -> bool:
        """Check if the modem responds to AT commands."""
        try:
            return self._at.ping()
        except Exception as exc:
            logger.error("Modem probe failed: {}", exc)
            return False

    def get_state(self) -> ModemState:
        """Return the current modem state."""
        return self._state

    def open(self) -> None:
        """Open the serial transport."""
        self._transport.open()
        self._state.phase = ModemPhase.PROBING

    def close(self) -> None:
        """Shut down PPP, radio, and serial transport."""
        self.stop_ppp()
        try:
            self._at.hangup()
        except Exception:
            pass
        self._transport.close()
        self._state.phase = ModemPhase.OFF

    def init_modem(self) -> None:
        """Run the full modem initialization sequence."""
        self._state.phase = ModemPhase.READY
        self._at.echo_off()

        self._state.sim_ready = self._at.check_sim()
        if not self._state.sim_ready:
            self._state.error = "SIM not ready"
            logger.error("SIM not ready")
            return

        self._state.phase = ModemPhase.REGISTERING
        self._state.signal = self._at.get_signal_quality()

        carrier, network_type = self._at.get_carrier()
        self._state.carrier = carrier
        self._state.network_type = network_type

        if not self._at.get_registration():
            self._state.error = "Not registered on network"
            logger.error("Network registration failed")
            return

        self._state.phase = ModemPhase.REGISTERED
        self._state.error = ""
        logger.info(
            "Modem ready: carrier={}, type={}, signal={}bars",
            carrier,
            network_type,
            self._state.signal.bars,
        )

        if self._config.gps_enabled:
            self._at.enable_gps()

    def start_ppp(self) -> bool:
        """Configure PDP and start pppd."""
        self._state.phase = ModemPhase.PPP_STARTING
        self._at.configure_pdp(self._config.apn)

        if not self._ppp.spawn():
            self._state.phase = ModemPhase.REGISTERED
            self._state.error = "PPP failed to start"
            return False

        self._state.phase = ModemPhase.ONLINE
        self._state.error = ""
        return True

    def stop_ppp(self) -> None:
        """Stop the pppd process."""
        if self._ppp.is_alive():
            self._state.phase = ModemPhase.PPP_STOPPING
            self._ppp.kill()
            self._state.phase = ModemPhase.REGISTERED

    def query_gps(self) -> GpsCoordinate | None:
        """Query GPS. If PPP is active, briefly tear it down."""
        ppp_was_active = self._ppp.is_alive()
        if ppp_was_active:
            self.stop_ppp()

        coord = self._gps.query()
        if coord is not None:
            self._state.gps = coord

        if ppp_was_active:
            self.start_ppp()

        return coord
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_network_backend.py -v`
Expected: all 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/yoyopod/network/backend.py tests/test_network_backend.py
git commit -m "feat(network): add SIM7600 backend with probe, init, PPP, GPS"
```

---

## Task 7: Network Events and AppContext Integration

**Files:**
- Modify: `src/yoyopod/events.py`
- Modify: `src/yoyopod/app_context.py`
- Modify: `tests/test_network_models.py`

- [ ] **Step 1: Write failing test for events and AppContext**

Add to `tests/test_network_models.py`:

```python
from yoyopod.events import (
    NetworkModemReadyEvent,
    NetworkRegisteredEvent,
    NetworkPppUpEvent,
    NetworkPppDownEvent,
    NetworkSignalUpdateEvent,
    NetworkGpsFixEvent,
)
from yoyopod.app_context import AppContext


def test_network_events_are_frozen():
    """Network events should be immutable frozen dataclasses."""
    evt = NetworkPppUpEvent()
    try:
        evt.connection_type = "wifi"  # type: ignore
        assert False, "Expected FrozenInstanceError"
    except AttributeError:
        pass


def test_app_context_update_network_status():
    """update_network_status should set signal and connection fields."""
    ctx = AppContext()
    assert ctx.connection_type == "none"
    assert ctx.signal_strength == 4  # default

    ctx.update_network_status(signal_bars=3, connection_type="4g", connected=True)
    assert ctx.signal_strength == 3
    assert ctx.connection_type == "4g"
    assert ctx.is_connected is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_network_models.py::test_network_events_are_frozen -v`
Expected: FAIL with `ImportError: cannot import name 'NetworkModemReadyEvent'`

- [ ] **Step 3: Add network events**

Add to `src/yoyopod/events.py`:

```python
@dataclass(frozen=True, slots=True)
class NetworkModemReadyEvent:
    """Published when the modem is initialized and registered."""

    carrier: str = ""
    network_type: str = ""


@dataclass(frozen=True, slots=True)
class NetworkRegisteredEvent:
    """Published when the modem attaches to a cellular network."""

    carrier: str = ""
    network_type: str = ""


@dataclass(frozen=True, slots=True)
class NetworkPppUpEvent:
    """Published when PPP data session is established."""

    connection_type: str = "4g"


@dataclass(frozen=True, slots=True)
class NetworkPppDownEvent:
    """Published when PPP data session drops."""

    reason: str = ""


@dataclass(frozen=True, slots=True)
class NetworkSignalUpdateEvent:
    """Published when signal strength changes."""

    bars: int = 0
    csq: int = 0


@dataclass(frozen=True, slots=True)
class NetworkGpsFixEvent:
    """Published when a GPS coordinate is obtained."""

    lat: float = 0.0
    lng: float = 0.0
    altitude: float = 0.0
    speed: float = 0.0
```

- [ ] **Step 4: Add update_network_status to AppContext**

Add to `src/yoyopod/app_context.py` in the `AppContext` class:

```python
def update_network_status(
    self,
    *,
    signal_bars: int | None = None,
    connection_type: str | None = None,
    connected: bool | None = None,
) -> None:
    """Update cached network telemetry from the modem backend."""
    if signal_bars is not None:
        self.signal_strength = max(0, min(4, signal_bars))
    if connection_type is not None:
        self.connection_type = connection_type
    if connected is not None:
        self.is_connected = connected
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_network_models.py -v`
Expected: all 8 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/yoyopod/events.py src/yoyopod/app_context.py tests/test_network_models.py
git commit -m "feat(network): add network events and AppContext integration"
```

---

## Task 8: Network Manager Facade

**Files:**
- Create: `src/yoyopod/network/manager.py`
- Create: `tests/test_network_manager.py`
- Modify: `src/yoyopod/network/__init__.py`

- [ ] **Step 1: Write failing test for NetworkManager**

```python
# tests/test_network_manager.py
"""Unit tests for the NetworkManager facade."""

from __future__ import annotations

from yoyopod.config.models import AppNetworkConfig, build_config_model
from yoyopod.event_bus import EventBus
from yoyopod.events import NetworkPppUpEvent, NetworkPppDownEvent
from yoyopod.network.manager import NetworkManager
from yoyopod.network.models import ModemPhase, ModemState, SignalInfo


class FakeBackend:
    """Minimal backend double for manager tests."""

    def __init__(self) -> None:
        self.state = ModemState(
            phase=ModemPhase.ONLINE,
            signal=SignalInfo(csq=20),
            carrier="T-Mobile",
            network_type="4G",
            sim_ready=True,
        )
        self.opened = False
        self.closed = False
        self.inited = False
        self.ppp_started = False
        self.ppp_stopped = False

    def probe(self) -> bool:
        return True

    def get_state(self) -> ModemState:
        return self.state

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.closed = True

    def init_modem(self) -> None:
        self.inited = True
        self.state.phase = ModemPhase.REGISTERED

    def start_ppp(self) -> bool:
        self.ppp_started = True
        self.state.phase = ModemPhase.ONLINE
        return True

    def stop_ppp(self) -> None:
        self.ppp_stopped = True
        self.state.phase = ModemPhase.REGISTERED

    def query_gps(self):
        return None


def test_manager_start_full_sequence():
    """start() should open, init, and start PPP."""
    config = build_config_model(AppNetworkConfig, {"enabled": True, "apn": "internet"})
    backend = FakeBackend()
    bus = EventBus()
    manager = NetworkManager(config=config, backend=backend, event_bus=bus)

    manager.start()

    assert backend.opened is True
    assert backend.inited is True
    assert backend.ppp_started is True


def test_manager_stop():
    """stop() should close the backend."""
    config = build_config_model(AppNetworkConfig, {"enabled": True, "apn": "internet"})
    backend = FakeBackend()
    bus = EventBus()
    manager = NetworkManager(config=config, backend=backend, event_bus=bus)

    manager.start()
    manager.stop()

    assert backend.closed is True


def test_manager_publishes_ppp_up():
    """start() should publish NetworkPppUpEvent on the bus."""
    config = build_config_model(AppNetworkConfig, {"enabled": True, "apn": "internet"})
    backend = FakeBackend()
    bus = EventBus()
    events_seen: list[object] = []
    bus.subscribe(NetworkPppUpEvent, events_seen.append)

    manager = NetworkManager(config=config, backend=backend, event_bus=bus)
    manager.start()

    assert len(events_seen) == 1
    assert isinstance(events_seen[0], NetworkPppUpEvent)


def test_manager_is_online():
    """is_online should reflect backend PPP state."""
    config = build_config_model(AppNetworkConfig, {"enabled": True, "apn": "internet"})
    backend = FakeBackend()
    bus = EventBus()
    manager = NetworkManager(config=config, backend=backend, event_bus=bus)

    manager.start()
    assert manager.is_online is True

    backend.state.phase = ModemPhase.REGISTERED
    assert manager.is_online is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_network_manager.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yoyopod.network.manager'`

- [ ] **Step 3: Implement NetworkManager**

```python
# src/yoyopod/network/manager.py
"""App-facing network manager facade."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from yoyopod.network.backend import Sim7600Backend
from yoyopod.network.models import GpsCoordinate, ModemPhase, ModemState

if TYPE_CHECKING:
    from yoyopod.config import ConfigManager
    from yoyopod.config.models import AppNetworkConfig
    from yoyopod.event_bus import EventBus


class NetworkManager:
    """Coordinate modem backend access and publish events."""

    def __init__(
        self,
        config: "AppNetworkConfig",
        backend: object | None = None,
        event_bus: "EventBus | None" = None,
    ) -> None:
        self.config = config
        self.backend = backend or Sim7600Backend(config)
        self.event_bus = event_bus

    @classmethod
    def from_config_manager(
        cls, config_manager: "ConfigManager", event_bus: "EventBus | None" = None
    ) -> "NetworkManager":
        """Build a network manager from the typed app configuration."""
        config = config_manager.settings.network
        return cls(config=config, event_bus=event_bus)

    def start(self) -> None:
        """Open modem, initialize, and start PPP."""
        from yoyopod.events import (
            NetworkModemReadyEvent,
            NetworkPppUpEvent,
            NetworkRegisteredEvent,
            NetworkSignalUpdateEvent,
        )

        if not self.config.enabled:
            logger.info("Network module disabled")
            return

        logger.info("Starting network manager")
        self.backend.open()
        self.backend.init_modem()

        state = self.backend.get_state()
        if state.phase == ModemPhase.REGISTERED:
            self._publish(NetworkModemReadyEvent(
                carrier=state.carrier,
                network_type=state.network_type,
            ))
            self._publish(NetworkRegisteredEvent(
                carrier=state.carrier,
                network_type=state.network_type,
            ))
            if state.signal:
                self._publish(NetworkSignalUpdateEvent(
                    bars=state.signal.bars,
                    csq=state.signal.csq,
                ))

            if self.backend.start_ppp():
                self._publish(NetworkPppUpEvent(connection_type="4g"))
        else:
            logger.error("Modem init failed: {}", state.error)

    def stop(self) -> None:
        """Stop PPP and close the modem."""
        from yoyopod.events import NetworkPppDownEvent

        logger.info("Stopping network manager")
        try:
            self.backend.close()
        except Exception as exc:
            logger.error("Error stopping network: {}", exc)
        self._publish(NetworkPppDownEvent(reason="shutdown"))

    @property
    def is_online(self) -> bool:
        """Return True when PPP is up."""
        return self.backend.get_state().phase == ModemPhase.ONLINE

    @property
    def modem_state(self) -> ModemState:
        """Return the current modem state."""
        return self.backend.get_state()

    def query_gps(self) -> GpsCoordinate | None:
        """Query GPS coordinates (may briefly interrupt PPP)."""
        from yoyopod.events import NetworkGpsFixEvent

        coord = self.backend.query_gps()
        if coord is not None:
            self._publish(NetworkGpsFixEvent(
                lat=coord.lat,
                lng=coord.lng,
                altitude=coord.altitude,
                speed=coord.speed,
            ))
        return coord

    def _publish(self, event: object) -> None:
        """Publish an event if the bus is available."""
        if self.event_bus is not None:
            self.event_bus.publish(event)
```

- [ ] **Step 4: Update __init__.py exports**

```python
# src/yoyopod/network/__init__.py
"""4G cellular connectivity for YoyoPod."""

from yoyopod.network.backend import NetworkBackend, Sim7600Backend
from yoyopod.network.manager import NetworkManager
from yoyopod.network.models import GpsCoordinate, ModemPhase, ModemState, SignalInfo

__all__ = [
    "GpsCoordinate",
    "ModemPhase",
    "ModemState",
    "NetworkBackend",
    "NetworkManager",
    "SignalInfo",
    "Sim7600Backend",
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_network_manager.py -v`
Expected: all 4 tests PASS

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -q`
Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add src/yoyopod/network/manager.py src/yoyopod/network/__init__.py tests/test_network_manager.py
git commit -m "feat(network): add NetworkManager facade with EventBus integration"
```

---

## Task 9: App Bootstrap Wiring

**Files:**
- Modify: `src/yoyopod/app.py`

- [ ] **Step 1: Add NetworkManager to app.py imports**

Add to the imports in `src/yoyopod/app.py`:

```python
from yoyopod.network import NetworkManager
from yoyopod.events import NetworkPppUpEvent, NetworkPppDownEvent
```

- [ ] **Step 2: Add network_manager field to YoyoPodApp.__init__**

In the Manager components section around line 133, add:

```python
self.network_manager: Optional[NetworkManager] = None
```

- [ ] **Step 3: Wire NetworkManager into the startup method**

In the `_initialize_managers` or startup section of `app.py` (near where PowerManager is initialized around line 527), add after the power manager setup:

```python
logger.info("  - NetworkManager")
self.network_manager = NetworkManager.from_config_manager(
    self.config_manager, event_bus=self.event_bus
)
if self.network_manager.config.enabled and not self.simulate:
    try:
        self.network_manager.start()
        state = self.network_manager.modem_state
        if state.signal:
            self.context.update_network_status(
                signal_bars=state.signal.bars,
                connection_type="4g" if self.network_manager.is_online else "none",
                connected=self.network_manager.is_online,
            )
    except Exception as exc:
        logger.error("Network manager start failed: {}", exc)
```

- [ ] **Step 4: Wire VoIP to wait for PPP when network is enabled**

Subscribe to `NetworkPppUpEvent` in `__init__` to trigger VoIP registration:

```python
self.event_bus.subscribe(NetworkPppUpEvent, self._handle_network_ppp_up)
```

Add handler method:

```python
def _handle_network_ppp_up(self, event: NetworkPppUpEvent) -> None:
    """Start VoIP registration when PPP comes up."""
    if self.context:
        self.context.update_network_status(
            signal_bars=self.network_manager.modem_state.signal.bars if self.network_manager and self.network_manager.modem_state.signal else 0,
            connection_type="4g",
            connected=True,
        )
```

- [ ] **Step 5: Add cleanup to stop method**

In the app's stop/cleanup method, add before the existing cleanup:

```python
if self.network_manager is not None:
    try:
        self.network_manager.stop()
    except Exception as exc:
        logger.error("Network manager cleanup failed: {}", exc)
```

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -q`
Expected: all tests pass (network module is disabled by default, so no impact on existing tests)

- [ ] **Step 7: Commit**

```bash
git add src/yoyopod/app.py
git commit -m "feat(network): wire NetworkManager into app bootstrap"
```

---

## Task 10: CLI Commands

**Files:**
- Create: `src/yoyopod/cli/pi/network.py`
- Modify: `src/yoyopod/cli/__init__.py`

- [ ] **Step 1: Implement CLI commands**

```python
# src/yoyopod/cli/pi/network.py
"""src/yoyopod/cli/pi/network.py — SIM7600 modem and GPS commands."""

from __future__ import annotations

from typing import Annotated

import typer

from yoyopod.cli.common import configure_logging, resolve_config_dir

network_app = typer.Typer(name="network", help="SIM7600 modem and GPS commands.", no_args_is_help=True)


@network_app.command()
def probe(
    config_dir: Annotated[str, typer.Option("--config-dir", help="Configuration directory.")] = "config",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Check if the SIM7600 modem responds to AT commands."""
    from loguru import logger

    from yoyopod.config import ConfigManager
    from yoyopod.network import NetworkManager

    configure_logging(verbose)
    config_path = resolve_config_dir(config_dir)
    config_manager = ConfigManager(config_dir=str(config_path))
    manager = NetworkManager.from_config_manager(config_manager)

    if not manager.config.enabled:
        logger.error("network module disabled in yoyopod_config.yaml")
        raise typer.Exit(code=1)

    from yoyopod.network.transport import SerialTransport, TransportError

    transport = SerialTransport(
        port=manager.config.serial_port,
        baud_rate=manager.config.baud_rate,
    )
    try:
        transport.open()
        from yoyopod.network.at_commands import AtCommandSet

        at = AtCommandSet(transport)
        if at.ping():
            print("Modem OK")
        else:
            print("Modem did not respond")
            raise typer.Exit(code=1)
    except TransportError as exc:
        logger.error(str(exc))
        raise typer.Exit(code=1)
    finally:
        transport.close()


@network_app.command()
def status(
    config_dir: Annotated[str, typer.Option("--config-dir", help="Configuration directory.")] = "config",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Show modem status: signal, carrier, registration, PPP state."""
    from loguru import logger

    from yoyopod.config import ConfigManager
    from yoyopod.network import NetworkManager
    from yoyopod.network.backend import Sim7600Backend

    configure_logging(verbose)
    config_path = resolve_config_dir(config_dir)
    config_manager = ConfigManager(config_dir=str(config_path))
    manager = NetworkManager.from_config_manager(config_manager)

    if not manager.config.enabled:
        logger.error("network module disabled in yoyopod_config.yaml")
        raise typer.Exit(code=1)

    backend = Sim7600Backend(manager.config)
    try:
        backend.open()
        backend.init_modem()
        state = backend.get_state()

        print("")
        print("SIM7600 Modem Status")
        print("====================")
        lines = [
            f"phase={state.phase.value}",
            f"sim_ready={state.sim_ready}",
            f"carrier={state.carrier or 'unknown'}",
            f"network_type={state.network_type or 'unknown'}",
            f"signal_csq={state.signal.csq if state.signal else 'unknown'}",
            f"signal_bars={state.signal.bars if state.signal else 'unknown'}",
            f"error={state.error or 'none'}",
        ]
        for line in lines:
            print(line)
    except Exception as exc:
        logger.error(f"Modem status failed: {exc}")
        raise typer.Exit(code=1)
    finally:
        backend.close()


@network_app.command()
def gps(
    config_dir: Annotated[str, typer.Option("--config-dir", help="Configuration directory.")] = "config",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Query current GPS coordinates."""
    from loguru import logger

    from yoyopod.config import ConfigManager
    from yoyopod.network import NetworkManager
    from yoyopod.network.backend import Sim7600Backend

    configure_logging(verbose)
    config_path = resolve_config_dir(config_dir)
    config_manager = ConfigManager(config_dir=str(config_path))
    manager = NetworkManager.from_config_manager(config_manager)

    if not manager.config.enabled:
        logger.error("network module disabled in yoyopod_config.yaml")
        raise typer.Exit(code=1)

    backend = Sim7600Backend(manager.config)
    try:
        backend.open()
        backend.init_modem()
        coord = backend.query_gps()

        if coord is None:
            print("No GPS fix available")
            raise typer.Exit(code=1)

        print("")
        print("GPS Coordinates")
        print("===============")
        print(f"lat={coord.lat}")
        print(f"lng={coord.lng}")
        print(f"altitude={coord.altitude}")
        print(f"speed={coord.speed}")
    except Exception as exc:
        logger.error(f"GPS query failed: {exc}")
        raise typer.Exit(code=1)
    finally:
        backend.close()
```

- [ ] **Step 2: Register the network subcommand group**

In `src/yoyopod/cli/__init__.py`, find where `power_app` is added to the `pi_app` typer and add:

```python
from yoyopod.cli.pi.network import network_app

pi_app.add_typer(network_app)
```

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -q`
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add src/yoyopod/cli/pi/network.py src/yoyopod/cli/__init__.py
git commit -m "feat(network): add yoyopod pi network CLI commands"
```

---

## Task 11: Demo GPS Server

**Files:**
- Create: `demos/demo_gps_server.py`

- [ ] **Step 1: Implement demo GPS server**

```python
# demos/demo_gps_server.py
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

from yoyopod.config import ConfigManager
from yoyopod.network import NetworkManager
from yoyopod.network.backend import Sim7600Backend

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
```

- [ ] **Step 2: Commit**

```bash
git add demos/demo_gps_server.py
git commit -m "feat(network): add demo GPS server"
```

---

## Task 12: Pi Validation

**Files:** None (validation only)

- [ ] **Step 1: Enable UART on the Pi**

SSH to the Pi and verify UART is enabled:

```bash
ssh rpi-zero "cat /boot/config.txt | grep uart"
```

If `enable_uart=1` is missing, add it. Also verify Bluetooth doesn't claim the UART:

```bash
ssh rpi-zero "ls -la /dev/serial0 /dev/ttyS0 /dev/ttyAMA0 2>/dev/null"
```

- [ ] **Step 2: Install dependencies on the Pi**

```bash
ssh rpi-zero "sudo apt-get install -y ppp"
ssh rpi-zero "groups pi | grep dialout"
```

- [ ] **Step 3: Sync code to Pi**

Use the existing deploy workflow:

```bash
yoyopod remote sync --host rpi-zero
```

- [ ] **Step 4: Probe the modem**

```bash
ssh rpi-zero "cd /home/pi/yoyo-py && uv run yoyopod pi network probe"
```

Expected: `Modem OK`

- [ ] **Step 5: Check modem status**

```bash
ssh rpi-zero "cd /home/pi/yoyo-py && uv run yoyopod pi network status"
```

Expected: carrier name, signal bars, registered state

- [ ] **Step 6: Test GPS query** *(removed in 2026-04 CLI polish — use direct NMEA serial inspection or a one-off test script)*

- [ ] **Step 7: Run full test suite on Pi**

```bash
ssh rpi-zero "cd /home/pi/yoyo-py && uv run pytest -q"
```

Expected: all tests pass
