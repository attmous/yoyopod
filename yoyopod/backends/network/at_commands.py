"""Typed AT command builder and response parser for SIM7600G-H."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from yoyopod.integrations.network.models import GpsCoordinate, SignalInfo

if TYPE_CHECKING:
    from yoyopod.backends.network.transport import SerialTransport


def _ddmm_to_decimal(value: float) -> float:
    """Convert NMEA ddmm.mmmm format to decimal degrees."""

    degrees = int(value / 100)
    minutes = value - (degrees * 100)
    return degrees + minutes / 60.0


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
        return stat in ("1", "5")

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
            r"(\d+),"
            r"(\d+\.\d+),"
            r"(-?\d+\.?\d*),"
            r"(\d+\.?\d*),"
            r"",
            resp,
        )
        if not match:
            return None

        lat = _ddmm_to_decimal(float(match.group(1)))
        if match.group(2) == "S":
            lat = -lat
        lng = _ddmm_to_decimal(float(match.group(3)))
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


__all__ = ["AtCommandSet"]
