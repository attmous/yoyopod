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

            deadline = time.monotonic() + (
                timeout if timeout is not None else getattr(self, "timeout", 2.0)
            )
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


__all__ = ["SerialTransport", "TransportError"]
