"""Pi network commands backed by the Rust network host."""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Annotated, Any

import typer

from yoyopod.core.workers.protocol import encode_envelope, make_envelope, parse_envelope_line
from yoyopod_cli.common import configure_logging, resolve_config_dir

app = typer.Typer(name="network", help="Network host commands.", no_args_is_help=True)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STDOUT_EOF = object()


def _rust_network_host_worker_path() -> Path:
    raw_path = os.environ.get(
        "YOYOPOD_RUST_NETWORK_HOST_WORKER",
        "device/network/build/yoyopod-network-host",
    ).strip()
    worker_path = Path(raw_path)
    if not worker_path.is_absolute():
        worker_path = _REPO_ROOT / worker_path
    return worker_path


def _spawn_network_worker(config_dir: str) -> subprocess.Popen[str]:
    worker_path = _rust_network_host_worker_path()
    return subprocess.Popen(
        [str(worker_path), "--config-dir", str(resolve_config_dir(config_dir))],
        cwd=_REPO_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )


def _stop_network_worker(process: subprocess.Popen[str]) -> None:
    try:
        if process.poll() is None and process.stdin is not None:
            process.stdin.write(
                encode_envelope(
                    make_envelope(
                        kind="command",
                        type="network.shutdown",
                        request_id="shutdown-1",
                        payload={},
                    )
                )
            )
            process.stdin.flush()
    except (BrokenPipeError, OSError):
        pass

    try:
        process.wait(timeout=1.0)
        return
    except subprocess.TimeoutExpired:
        process.terminate()
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1.0)


def _read_worker_stdout(
    stdout: Any,
    line_queue: queue.Queue[str | object],
) -> None:
    try:
        while True:
            line = stdout.readline()
            if not line:
                return
            line_queue.put(line)
    finally:
        line_queue.put(_STDOUT_EOF)


def _worker_exit_error(process: subprocess.Popen[str]) -> str:
    stderr_text = ""
    if process.stderr is not None:
        stderr_text = process.stderr.read().strip()
    return stderr_text or "network worker exited before returning a snapshot"


def _snapshot_error_text(snapshot: dict[str, Any]) -> str:
    return str(snapshot.get("error_message", "") or snapshot.get("error_code", "") or "").strip()


def _cli_view(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    views = snapshot.get("views")
    if not isinstance(views, dict):
        return None
    cli_view = views.get("cli")
    if isinstance(cli_view, dict):
        return cli_view
    return None


def _ensure_snapshot_healthy(snapshot: dict[str, Any]) -> None:
    cli_view = _cli_view(snapshot)
    if not isinstance(cli_view, dict):
        raise RuntimeError("network snapshot missing Rust cli projection")
    error_text = str(cli_view.get("probe_error", "") or "").strip() or _snapshot_error_text(
        snapshot
    )
    if error_text:
        raise RuntimeError(error_text)
    if bool(cli_view.get("probe_ok", False)):
        return
    raise RuntimeError("network host reported unhealthy probe")


def _cli_status_lines(snapshot: dict[str, Any]) -> list[str]:
    cli_view = _cli_view(snapshot)
    if not isinstance(cli_view, dict):
        raise RuntimeError("network snapshot missing Rust cli projection")
    raw_lines = cli_view.get("status_lines")
    if not isinstance(raw_lines, list):
        raise RuntimeError("network snapshot missing Rust cli status lines")
    return [str(line) for line in raw_lines]


def _request_network_snapshot(config_dir: str, *, timeout_seconds: float = 10.0) -> dict[str, Any]:
    process = _spawn_network_worker(config_dir)
    latest_snapshot: dict[str, Any] | None = None
    stdout_reader: threading.Thread | None = None
    try:
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("network worker did not expose stdio")

        line_queue: queue.Queue[str | object] = queue.Queue()
        stdout_reader = threading.Thread(
            target=_read_worker_stdout,
            args=(process.stdout, line_queue),
            daemon=True,
            name="network-cli-stdout",
        )
        stdout_reader.start()

        process.stdin.write(
            encode_envelope(
                make_envelope(
                    kind="command",
                    type="network.health",
                    request_id="health-1",
                    payload={},
                )
            )
        )
        process.stdin.flush()

        deadline = time.monotonic() + max(0.1, float(timeout_seconds))
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            if remaining <= 0.0:
                break

            try:
                queued_line = line_queue.get(timeout=min(0.1, max(0.01, remaining)))
            except queue.Empty:
                if process.poll() is not None:
                    if latest_snapshot is not None:
                        return latest_snapshot
                    raise RuntimeError(_worker_exit_error(process))
                continue

            if queued_line is _STDOUT_EOF:
                if process.poll() is not None:
                    if latest_snapshot is not None:
                        return latest_snapshot
                    raise RuntimeError(_worker_exit_error(process))
                continue

            envelope = parse_envelope_line(str(queued_line))
            if envelope.type == "network.snapshot":
                snapshot_payload = envelope.payload.get("snapshot", envelope.payload)
                if isinstance(snapshot_payload, dict):
                    latest_snapshot = dict(snapshot_payload)
            elif envelope.type == "network.health" and envelope.kind == "result":
                snapshot_payload = envelope.payload.get("snapshot")
                if isinstance(snapshot_payload, dict):
                    return dict(snapshot_payload)
            elif envelope.kind == "error":
                code = str(envelope.payload.get("code", "") or "").strip()
                message = str(envelope.payload.get("message", "") or "").strip()
                raise RuntimeError(message or code or "network worker returned an error")

        if latest_snapshot is not None:
            return latest_snapshot
        raise RuntimeError("timed out waiting for network worker snapshot")
    finally:
        _stop_network_worker(process)
        if stdout_reader is not None:
            stdout_reader.join(timeout=0.2)


@app.command()
def probe(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory.")
    ] = "config",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Check if the Rust network host can bring up the modem domain."""

    from loguru import logger

    configure_logging(verbose)
    try:
        snapshot = _request_network_snapshot(config_dir)
        _ensure_snapshot_healthy(snapshot)
    except Exception as exc:
        logger.error(str(exc))
        raise typer.Exit(code=1) from exc

    print("Modem OK")


@app.command()
def status(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory.")
    ] = "config",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Show current cellular status from the Rust network host."""

    from loguru import logger

    configure_logging(verbose)
    try:
        snapshot = _request_network_snapshot(config_dir)
        _ensure_snapshot_healthy(snapshot)
    except Exception as exc:
        logger.error(f"Modem status failed: {exc}")
        raise typer.Exit(code=1) from exc

    lines = _cli_status_lines(snapshot)

    print("")
    print("Rust Network Host Status")
    print("========================")
    for line in lines:
        print(line)
