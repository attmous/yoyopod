"""Tests for mpv JSON IPC client."""

from __future__ import annotations

import json
import queue
import socket
import threading
import time
from pathlib import Path
from unittest.mock import patch

from yoyopod.audio.music.ipc import MpvIpcClient


def _make_socket_pair(tmp_path: Path) -> tuple[str, socket.socket]:
    """Create a Unix socket server for testing."""
    sock_path = str(tmp_path / "test-mpv.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    server.listen(1)
    return sock_path, server


class _FakeSocket:
    def __init__(self) -> None:
        self._next_recv = b""
        self._has_data = threading.Event()

    def connect(self, socket_path: str) -> None:
        self.socket_path = socket_path

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def sendall(self, data: bytes) -> None:
        request = json.loads(data.decode().strip())
        response = {
            "request_id": request["request_id"],
            "error": "success",
            "data": "0.38.0",
        }
        self._next_recv = (json.dumps(response) + "\n").encode()
        self._has_data.set()

    def recv(self, size: int) -> bytes:
        self._has_data.wait(timeout=1.0)
        chunk = self._next_recv
        self._next_recv = b""
        self._has_data.clear()
        return chunk

    def close(self) -> None:
        return None


class _FakeEventSocket(_FakeSocket):
    def __init__(self) -> None:
        super().__init__()
        self._event_sent = False

    def recv(self, size: int) -> bytes:
        if not self._event_sent:
            self._event_sent = True
            return (json.dumps({"event": "file-loaded"}) + "\n").encode()
        return b""


class _FakeEventThenResponseSocket(_FakeSocket):
    def __init__(self) -> None:
        super().__init__()
        self._responses: queue.Queue[bytes] = queue.Queue()
        self._responses.put((json.dumps({"event": "file-loaded"}) + "\n").encode())

    def sendall(self, data: bytes) -> None:
        request = json.loads(data.decode().strip())
        response = {
            "request_id": request["request_id"],
            "error": "success",
            "data": "/music/alpha.ogg",
        }
        self._responses.put((json.dumps(response) + "\n").encode())

    def recv(self, size: int) -> bytes:
        try:
            return self._responses.get(timeout=1.0)
        except queue.Empty:
            return b""


def test_connect_and_send_command(tmp_path: Path) -> None:
    if not hasattr(socket, "AF_UNIX"):
        fake_socket = _FakeSocket()
        with patch.object(socket, "AF_UNIX", 1, create=True), patch(
            "yoyopod.audio.music.ipc.socket.socket",
            return_value=fake_socket,
        ):
            client = MpvIpcClient(str(tmp_path / "test-mpv.sock"))
            assert client.connect() is True
            result = client.send_command(["get_property", "mpv-version"])
            assert result["data"] == "0.38.0"
            client.disconnect()
        return

    sock_path, server = _make_socket_pair(tmp_path)

    def handle_client() -> None:
        conn, _ = server.accept()
        data = conn.recv(4096)
        request = json.loads(data.decode().strip())
        response = {"request_id": request["request_id"], "error": "success", "data": "0.38.0"}
        conn.sendall((json.dumps(response) + "\n").encode())
        conn.close()

    t = threading.Thread(target=handle_client, daemon=True)
    t.start()

    client = MpvIpcClient(sock_path)
    assert client.connect() is True
    result = client.send_command(["get_property", "mpv-version"])
    assert result["data"] == "0.38.0"
    client.disconnect()
    server.close()


def test_connect_fails_on_missing_socket(tmp_path: Path) -> None:
    client = MpvIpcClient(str(tmp_path / "nonexistent.sock"))
    assert client.connect() is False


def test_event_callback_fires(tmp_path: Path) -> None:
    if not hasattr(socket, "AF_UNIX"):
        fake_socket = _FakeEventSocket()
        events_received: list[dict] = []
        with patch.object(socket, "AF_UNIX", 1, create=True), patch(
            "yoyopod.audio.music.ipc.socket.socket",
            return_value=fake_socket,
        ):
            client = MpvIpcClient(str(tmp_path / "test-mpv.sock"))
            client.on_event(events_received.append)
            client.connect()
            client.start_reader()

            import time

            time.sleep(0.3)
            client.disconnect()

        assert len(events_received) >= 1
        assert events_received[0]["event"] == "file-loaded"
        return

    sock_path, server = _make_socket_pair(tmp_path)
    events_received: list[dict] = []

    def handle_client() -> None:
        conn, _ = server.accept()
        event = {"event": "file-loaded"}
        conn.sendall((json.dumps(event) + "\n").encode())
        import time

        time.sleep(0.2)
        conn.close()

    t = threading.Thread(target=handle_client, daemon=True)
    t.start()

    client = MpvIpcClient(sock_path)
    client.on_event(events_received.append)
    client.connect()
    client.start_reader()

    import time

    time.sleep(0.3)

    client.disconnect()
    server.close()

    assert len(events_received) >= 1
    assert events_received[0]["event"] == "file-loaded"


def test_event_callback_can_send_command_without_blocking_reader_thread(tmp_path: Path) -> None:
    fake_socket = _FakeEventThenResponseSocket()
    callback_results: list[str] = []

    with patch.object(socket, "AF_UNIX", 1, create=True), patch(
        "yoyopod.audio.music.ipc.socket.socket",
        return_value=fake_socket,
    ):
        client = MpvIpcClient(str(tmp_path / "test-mpv.sock"))

        def handle_event(_event: dict[str, object]) -> None:
            result = client.send_command(["get_property", "path"], timeout=0.5)
            callback_results.append(str(result["data"]))

        client.on_event(handle_event)
        assert client.connect() is True

        deadline = time.time() + 1.0
        while time.time() < deadline and not callback_results:
            time.sleep(0.01)

        client.disconnect()

    assert callback_results == ["/music/alpha.ogg"]


def test_disconnect_is_safe_when_not_connected(tmp_path: Path) -> None:
    client = MpvIpcClient(str(tmp_path / "no.sock"))
    client.disconnect()


def test_disconnect_wakes_blocked_dispatch_thread(tmp_path: Path) -> None:
    client = MpvIpcClient(str(tmp_path / "no.sock"))
    client._event_queue = queue.Queue()
    client._dispatch_thread = threading.Thread(target=client._dispatch_loop, daemon=True)
    client._dispatch_thread.start()

    deadline = time.time() + 1.0
    while time.time() < deadline and not client._dispatch_thread.is_alive():
        time.sleep(0.01)

    assert client._dispatch_thread.is_alive() is True

    client.disconnect()

    assert client._dispatch_thread is None
