"""mpv JSON IPC client over Unix socket."""

from __future__ import annotations

import json
import queue
import socket
import threading
from typing import Any, BinaryIO, Callable

from loguru import logger


class MpvIpcClient:
    """Low-level client for mpv's JSON IPC protocol."""

    def __init__(self, socket_path: str) -> None:
        self.socket_path = socket_path
        self._sock: socket.socket | BinaryIO | None = None
        self._lock = threading.Lock()
        self._reader_thread: threading.Thread | None = None
        self._dispatch_thread: threading.Thread | None = None
        self._reader_stop = threading.Event()
        self._request_id = 0
        self._pending: dict[int, threading.Event] = {}
        self._responses: dict[int, dict[str, Any]] = {}
        self._event_callbacks: list[Callable[[dict[str, Any]], None]] = []
        self._event_queue: queue.Queue[dict[str, Any] | None] | None = None

    def connect(self) -> bool:
        """Connect to the mpv IPC socket."""
        try:
            if self.socket_path.startswith("\\\\.\\pipe\\"):
                self._sock = open(self.socket_path, "r+b", buffering=0)
                logger.info("Connected to mpv named pipe: {}", self.socket_path)
            else:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.connect(self.socket_path)
                sock.settimeout(5.0)
                self._sock = sock
                logger.info("Connected to mpv IPC: {}", self.socket_path)

            self.start_reader()
            return True
        except Exception as exc:
            logger.error("Failed to connect to mpv IPC at {}: {}", self.socket_path, exc)
            self._sock = None
            return False

    def disconnect(self) -> None:
        """Close the socket and stop the reader thread."""
        self._reader_stop.set()

        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass

        if self._reader_thread is not None:
            self._reader_thread.join(timeout=2.0)
            self._reader_thread = None

        event_queue = self._event_queue
        self._event_queue = None
        if event_queue is not None:
            try:
                event_queue.put_nowait(None)
            except Exception:
                pass

        if self._dispatch_thread is not None:
            self._dispatch_thread.join(timeout=2.0)
            self._dispatch_thread = None

    @property
    def connected(self) -> bool:
        """Return True when the socket is open."""
        return self._sock is not None

    def send_command(self, args: list[object], timeout: float = 5.0) -> dict[str, Any]:
        """Send a command and wait for the response."""
        if self._sock is None:
            raise ConnectionError("mpv IPC is not connected")

        with self._lock:
            self._request_id += 1
            req_id = self._request_id

        ready = threading.Event()
        self._pending[req_id] = ready

        payload = json.dumps({"command": args, "request_id": req_id}) + "\n"
        try:
            self._send_data(payload.encode())
        except Exception as exc:
            self._pending.pop(req_id, None)
            raise ConnectionError(f"Failed to send mpv command: {exc}") from exc

        if not ready.wait(timeout):
            self._pending.pop(req_id, None)
            raise TimeoutError(f"mpv command timed out: {args}")

        return self._responses.pop(req_id, {})

    def observe_property(self, name: str, observe_id: int | None = None) -> None:
        """Ask mpv to push property-change events for the named property."""
        oid = observe_id if observe_id is not None else hash(name) & 0x7FFFFFFF
        self.send_command(["observe_property", oid, name])

    def on_event(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Register a callback for mpv events."""
        if callback not in self._event_callbacks:
            self._event_callbacks.append(callback)

    def start_reader(self) -> None:
        """Start the background thread that reads responses and events."""
        if self._reader_thread is not None:
            return
        self._reader_stop.clear()
        self._event_queue = queue.Queue()
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            daemon=True,
            name="mpv-ipc-reader",
        )
        self._reader_thread.start()
        self._dispatch_thread = threading.Thread(
            target=self._dispatch_loop,
            daemon=True,
            name="mpv-ipc-dispatch",
        )
        self._dispatch_thread.start()

    def _send_data(self, data: bytes) -> None:
        """Write raw bytes to the connected transport."""
        if self._sock is None:
            raise ConnectionError("mpv IPC is not connected")
        if hasattr(self._sock, "sendall"):
            self._sock.sendall(data)
            return
        self._sock.write(data)
        self._sock.flush()

    def _read_chunk(self) -> bytes:
        """Read raw bytes from the connected transport."""
        if self._sock is None:
            return b""
        if hasattr(self._sock, "recv"):
            return self._sock.recv(4096)
        return self._sock.read(4096)

    def _reader_loop(self) -> None:
        """Read newline-delimited JSON from the socket."""
        buffer = ""
        while not self._reader_stop.is_set():
            try:
                chunk = self._read_chunk()
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if "request_id" in msg:
                        req_id = msg["request_id"]
                        self._responses[req_id] = msg
                        event = self._pending.pop(req_id, None)
                        if event is not None:
                            event.set()
                    elif "event" in msg:
                        event_queue = self._event_queue
                        if event_queue is not None:
                            event_queue.put(msg)
            except socket.timeout:
                continue
            except Exception:
                if not self._reader_stop.is_set():
                    logger.warning("mpv IPC reader disconnected")
                break

    def _dispatch_loop(self) -> None:
        """Invoke event callbacks outside the socket reader thread."""
        event_queue = self._event_queue
        if event_queue is None:
            return

        while True:
            event = event_queue.get()
            if event is None:
                break

            for cb in list(self._event_callbacks):
                try:
                    cb(event)
                except Exception as exc:
                    logger.error("mpv event callback error: {}", exc)


__all__ = ["MpvIpcClient"]
