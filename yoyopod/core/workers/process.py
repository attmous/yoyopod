"""One child-process runtime for NDJSON worker sidecars."""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from queue import Empty, Full, Queue
from typing import IO

from loguru import logger

from yoyopod.core.workers.protocol import (
    WorkerEnvelope,
    WorkerProtocolError,
    encode_envelope,
    make_envelope,
    parse_envelope_line,
)


@dataclass(frozen=True, slots=True)
class WorkerProcessConfig:
    """Configuration for one managed worker process."""

    name: str
    argv: list[str]
    cwd: str | None = None
    env: dict[str, str] | None = None
    receive_queue_size: int = 64


@dataclass(frozen=True, slots=True)
class WorkerProcessSnapshot:
    """Observable state for one worker process."""

    name: str
    running: bool
    pid: int | None
    returncode: int | None
    received_messages: int
    protocol_errors: int
    dropped_messages: int
    stderr_lines: int
    terminated: bool
    killed: bool


class WorkerProcessRuntime:
    """Manage stdio for one worker child process without blocking the UI loop."""

    def __init__(self, config: WorkerProcessConfig) -> None:
        self.config = config
        self._process: subprocess.Popen[str] | None = None
        self._messages: Queue[WorkerEnvelope] = Queue(maxsize=max(1, config.receive_queue_size))
        self._stdin_lock = threading.Lock()
        self._reader_threads: list[threading.Thread] = []
        self._received_messages = 0
        self._protocol_errors = 0
        self._dropped_messages = 0
        self._stderr_lines = 0
        self._terminated = False
        self._killed = False

    @property
    def running(self) -> bool:
        """Return whether the child process is still alive."""

        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        """Start the child process and stdout/stderr reader threads."""

        if self.running:
            return
        self._process = subprocess.Popen(
            self.config.argv,
            cwd=self.config.cwd,
            env=self.config.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert self._process.stdout is not None
        assert self._process.stderr is not None
        self._reader_threads = [
            self._start_reader("stdout", self._process.stdout),
            self._start_reader("stderr", self._process.stderr),
        ]

    def send_command(
        self,
        *,
        type: str,
        payload: dict[str, object] | None = None,
        request_id: str | None = None,
        timestamp_ms: int = 0,
        deadline_ms: int = 0,
    ) -> bool:
        """Write one command envelope to worker stdin."""

        envelope = make_envelope(
            kind="command",
            type=type,
            payload=payload,
            request_id=request_id,
            timestamp_ms=timestamp_ms,
            deadline_ms=deadline_ms,
        )
        return self.send(envelope)

    def send(self, envelope: WorkerEnvelope) -> bool:
        """Write one envelope to worker stdin and report whether it was accepted."""

        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            return False
        with self._stdin_lock:
            try:
                process.stdin.write(encode_envelope(envelope))
                process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                return False
        return True

    def drain_messages(self, limit: int | None = None) -> list[WorkerEnvelope]:
        """Return available worker messages without blocking."""

        messages: list[WorkerEnvelope] = []
        while limit is None or len(messages) < limit:
            try:
                messages.append(self._messages.get_nowait())
            except Empty:
                break
        return messages

    def wait_for_messages(
        self,
        *,
        count: int,
        timeout_seconds: float,
    ) -> list[WorkerEnvelope]:
        """Testing helper that waits for a small number of messages."""

        deadline = time.monotonic() + timeout_seconds
        messages: list[WorkerEnvelope] = []
        while len(messages) < count and time.monotonic() < deadline:
            messages.extend(self.drain_messages(limit=count - len(messages)))
            if len(messages) >= count:
                break
            time.sleep(0.01)
        return messages

    def wait_until_exited(self, *, timeout_seconds: float) -> bool:
        """Testing helper that waits for process exit."""

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self._process is None or self._process.poll() is not None:
                return True
            time.sleep(0.01)
        return False

    def stop(self, *, grace_seconds: float = 1.0) -> None:
        """Stop the worker with bounded terminate/kill behavior."""

        process = self._process
        if process is None:
            return
        if process.poll() is None:
            envelope = make_envelope(
                kind="command",
                type="worker.stop",
                payload={},
                deadline_ms=int(grace_seconds * 1000),
            )
            self._send_with_lock_timeout(envelope, timeout_seconds=min(0.05, grace_seconds))
            deadline = time.monotonic() + max(0.0, grace_seconds)
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
        if process.poll() is None:
            process.terminate()
            self._terminated = True
            try:
                process.wait(timeout=max(0.05, grace_seconds))
            except subprocess.TimeoutExpired:
                process.kill()
                self._killed = True
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    logger.warning("worker {} did not exit after kill", self.config.name)
        self._join_readers(timeout_seconds=0.2)

    def _send_with_lock_timeout(
        self,
        envelope: WorkerEnvelope,
        *,
        timeout_seconds: float,
    ) -> bool:
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            return False
        acquired = self._stdin_lock.acquire(timeout=max(0.0, timeout_seconds))
        if not acquired:
            logger.debug("worker {} graceful stop skipped; stdin lock busy", self.config.name)
            return False
        try:
            if process.poll() is not None:
                return False
            try:
                process.stdin.write(encode_envelope(envelope))
                process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                return False
        finally:
            self._stdin_lock.release()
        return True

    def snapshot(self) -> WorkerProcessSnapshot:
        """Return the observable process state."""

        process = self._process
        return WorkerProcessSnapshot(
            name=self.config.name,
            running=self.running,
            pid=process.pid if process is not None else None,
            returncode=process.poll() if process is not None else None,
            received_messages=self._received_messages,
            protocol_errors=self._protocol_errors,
            dropped_messages=self._dropped_messages,
            stderr_lines=self._stderr_lines,
            terminated=self._terminated,
            killed=self._killed,
        )

    def _start_reader(self, stream_name: str, stream: IO[str]) -> threading.Thread:
        thread = threading.Thread(
            target=self._read_stream,
            args=(stream_name, stream),
            name=f"yoyopod-worker-{self.config.name}-{stream_name}",
            daemon=True,
        )
        thread.start()
        return thread

    def _read_stream(self, stream_name: str, stream: IO[str]) -> None:
        for line in stream:
            if stream_name == "stderr":
                self._stderr_lines += 1
                logger.info("worker {} stderr: {}", self.config.name, line.rstrip())
                continue
            try:
                envelope = parse_envelope_line(line)
            except WorkerProtocolError:
                self._protocol_errors += 1
                continue
            try:
                self._messages.put_nowait(envelope)
                self._received_messages += 1
            except Full:
                self._dropped_messages += 1

    def _join_readers(self, *, timeout_seconds: float) -> None:
        for thread in self._reader_threads:
            thread.join(timeout=timeout_seconds)
