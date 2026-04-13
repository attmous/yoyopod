"""pppd subprocess lifecycle manager."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from loguru import logger


class PppProcess:
    """Spawn, monitor, and kill a pppd process for cellular data."""

    _PPP_BINARY_CANDIDATES = ("pppd", "/usr/sbin/pppd", "/sbin/pppd")

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

        pppd_binary = self._resolve_pppd_binary()
        if pppd_binary is None:
            logger.error("pppd binary not found")
            return False

        cmd = [
            pppd_binary,
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

    def _resolve_pppd_binary(self) -> str | None:
        """Find pppd even when systemd omits sbin directories from PATH."""

        for candidate in self._PPP_BINARY_CANDIDATES:
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
            if candidate.startswith("/") and Path(candidate).exists():
                return candidate
        return None

    def wait_for_link(self, timeout: float = 30.0) -> bool:
        """Block until ppp0 interface exists or timeout expires."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.is_alive():
                logger.error("pppd exited during link negotiation")
                return False
            if Path("/sys/class/net/ppp0").exists():
                logger.info("ppp0 interface is up")
                return True
            time.sleep(1.0)
        logger.error("ppp0 did not come up within {}s", timeout)
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
