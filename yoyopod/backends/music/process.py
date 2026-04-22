"""mpv process lifecycle manager."""

from __future__ import annotations

import subprocess
from pathlib import Path

from loguru import logger

from yoyopod.backends.music.models import MusicConfig


class MpvProcess:
    """Spawn, monitor, and kill an mpv process for music playback."""

    def __init__(self, config: MusicConfig) -> None:
        self.config = config
        self._process: subprocess.Popen | None = None

    def spawn(self) -> bool:
        """Launch mpv in idle mode with IPC socket."""
        if self._process is not None and self._process.poll() is None:
            logger.warning("mpv process already running (pid={})", self._process.pid)
            return True

        self._clean_stale_socket()

        cmd = [
            self.config.mpv_binary,
            "--idle",
            "--no-video",
            f"--input-ipc-server={self.config.mpv_socket}",
            f"--audio-device=alsa/{self.config.alsa_device}",
        ]

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("mpv spawned (pid={}, socket={})", self._process.pid, self.config.mpv_socket)
            return True
        except FileNotFoundError:
            logger.error("mpv binary not found at '{}'", self.config.mpv_binary)
            return False
        except Exception as exc:
            logger.error("Failed to spawn mpv: {}", exc)
            return False

    def is_alive(self) -> bool:
        """Return True when the mpv process is running."""
        return self._process is not None and self._process.poll() is None

    def kill(self) -> None:
        """Terminate the mpv process and clean up the socket file."""
        if self._process is None:
            return

        try:
            self._process.terminate()
            self._process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            logger.warning("mpv did not exit after SIGTERM, sending SIGKILL")
            self._process.kill()
            self._process.wait(timeout=2.0)
        except Exception as exc:
            logger.error("Error killing mpv: {}", exc)
        finally:
            self._process = None
            self._clean_stale_socket()

    def respawn(self) -> bool:
        """Kill the current process and spawn a fresh one."""
        self.kill()
        return self.spawn()

    def _clean_stale_socket(self) -> None:
        """Remove a leftover socket file if present."""
        if self.config.mpv_socket.startswith("\\\\.\\pipe\\"):
            return

        sock = Path(self.config.mpv_socket)
        if sock.exists():
            try:
                sock.unlink()
            except OSError:
                pass


__all__ = ["MpvProcess"]
