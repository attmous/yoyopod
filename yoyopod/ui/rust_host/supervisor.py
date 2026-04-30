"""Subprocess supervisor for the Rust UI host."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import subprocess

from yoyopod.ui.rust_host.protocol import UiEnvelope, UiProtocolError


class RustUiHostError(RuntimeError):
    """Raised when the Rust UI host cannot be controlled."""


@dataclass(slots=True)
class RustUiHostSupervisor:
    argv: list[str]
    cwd: Path | None = None
    env: Mapping[str, str] | None = None
    ready_timeout_seconds: float = 5.0
    process: subprocess.Popen[str] | None = None

    def start(self) -> UiEnvelope:
        if self.process is not None and self.process.poll() is None:
            raise RustUiHostError("Rust UI host is already running")

        self.process = subprocess.Popen(
            self.argv,
            cwd=str(self.cwd) if self.cwd is not None else None,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=dict(self.env) if self.env is not None else None,
        )
        return self.read_event()

    def send(self, envelope: UiEnvelope) -> None:
        process = self._require_process()
        if process.stdin is None:
            raise RustUiHostError("Rust UI host stdin is not available")
        process.stdin.write(envelope.to_json_line())
        process.stdin.flush()

    def read_event(self) -> UiEnvelope:
        process = self._require_process()
        if process.stdout is None:
            raise RustUiHostError("Rust UI host stdout is not available")
        line = process.stdout.readline()
        if not line:
            raise RustUiHostError("Rust UI host exited before emitting an event")
        try:
            return UiEnvelope.from_json_line(line)
        except UiProtocolError as exc:
            raise RustUiHostError(str(exc)) from exc

    def stop(self, timeout_seconds: float = 2.0) -> None:
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            try:
                self.send(UiEnvelope.command("ui.shutdown"))
            except Exception:
                pass
            process.terminate()
            try:
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)
        self.process = None

    def _require_process(self) -> subprocess.Popen[str]:
        if self.process is None:
            raise RustUiHostError("Rust UI host is not running")
        return self.process
