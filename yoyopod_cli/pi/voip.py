"""On-device VoIP diagnostics — check registration, debug incoming calls."""

from __future__ import annotations

import time
from typing import Any, Callable, Protocol, cast

import typer

from yoyopod_cli.common import configure_logging
from yoyopod_cli.pi.support.call_models import CallState

app = typer.Typer(
    name="voip",
    help="On-device VoIP diagnostics.",
    no_args_is_help=True,
)


class _VoIPManagerLike(Protocol):
    """Minimal manager surface needed by the diagnostic helpers."""

    config: Any
    running: bool

    def start(self) -> bool: ...

    def stop(self) -> None: ...

    def iterate(self) -> int: ...

    def get_status(self) -> dict[str, Any]: ...

    def get_iterate_metrics(self) -> object | None: ...

    def on_registration_change(
        self,
        callback: Callable[[Any], None],
    ) -> None: ...

    def on_runtime_snapshot_change(
        self,
        callback: Callable[[Any], None],
    ) -> None: ...

    def make_call(self, sip_address: str, contact_name: str | None = None) -> bool: ...

    def hangup(self) -> bool: ...

    def get_call_duration(self) -> int: ...


def _build_voip_manager(config_dir: str) -> _VoIPManagerLike:
    from loguru import logger

    from yoyopod_cli.pi.rust_voip_runtime import build_rust_voip_manager

    try:
        return cast(_VoIPManagerLike, build_rust_voip_manager(config_dir))
    except RuntimeError as exc:
        logger.error(str(exc))
        raise typer.Exit(code=1)


def _enum_value(value: object) -> str:
    """Return a stable value string for enum-like runtime snapshots."""

    return str(getattr(value, "value", value or ""))


@app.command()
def check(
    config_dir: str = typer.Option(
        "config",
        "--config-dir",
        help="Configuration directory to use.",
    ),
) -> None:
    """Run a verbose SIP registration check against the Rust VoIP runtime."""
    from loguru import logger

    configure_logging(verbose=True)

    logger.info("=" * 60)
    logger.info("Rust VoIP Registration Test")
    logger.info("=" * 60)

    voip_manager = _build_voip_manager(config_dir)
    voip_config = voip_manager.config

    logger.info(f"SIP Server: {voip_config.sip_server}")
    logger.info(f"SIP Username: {voip_config.sip_username}")
    logger.info(f"SIP Identity: {voip_config.sip_identity}")
    logger.info(f"Transport: {voip_config.transport}")
    logger.info(f"STUN Server: {voip_config.stun_server}")
    logger.info(f"File transfer server: {voip_config.file_transfer_server_url or 'unset'}")

    registration_states: list[Any] = []
    voip_manager.on_registration_change(lambda state: registration_states.append(state))

    try:
        if not voip_manager.start():
            logger.error("Failed to start VoIP manager")
            raise typer.Exit(code=1)

        deadline = time.time() + 10.0
        while time.time() < deadline:
            voip_manager.iterate()
            status = voip_manager.get_status()
            if status["registered"]:
                logger.success("Registration successful")
                logger.success(f"State history: {[state.value for state in registration_states]}")
                return
            time.sleep(max(0.01, voip_config.iterate_interval_ms / 1000.0))

        status = voip_manager.get_status()
        logger.error("Registration failed or timed out")
        logger.error(f"State: {status['registration_state']}")
        logger.error(f"History: {[state.value for state in registration_states]}")
        raise typer.Exit(code=1)
    finally:
        voip_manager.stop()


@app.command()
def debug(
    config_dir: str = typer.Option(
        "config",
        "--config-dir",
        help="Configuration directory to use.",
    ),
) -> None:
    """Monitor for incoming SIP calls with verbose logging."""
    from loguru import logger

    configure_logging(verbose=True)

    logger.info("=" * 60)
    logger.info("Incoming Call Debug Test")
    logger.info("=" * 60)

    voip_manager = _build_voip_manager(config_dir)
    voip_config = voip_manager.config
    incoming_calls: list[tuple[str, str]] = []
    seen_call_ids: set[str] = set()

    def on_runtime_snapshot(snapshot: Any) -> None:
        if _enum_value(getattr(snapshot, "call_state", None)) != CallState.INCOMING.value:
            return
        call_id = str(getattr(snapshot, "active_call_id", "") or "")
        if call_id and call_id in seen_call_ids:
            return
        if call_id:
            seen_call_ids.add(call_id)
        caller_address = str(getattr(snapshot, "active_call_peer", "") or "")
        if not caller_address:
            session = getattr(snapshot, "call_session", None)
            caller_address = str(getattr(session, "peer_sip_address", "") or "")
        caller_name = caller_address or "Unknown"
        logger.success("=" * 60)
        logger.success("INCOMING CALL SNAPSHOT RECEIVED")
        logger.success(f"  Address: {caller_address}")
        logger.success(f"  Name: {caller_name}")
        logger.success("=" * 60)
        incoming_calls.append((caller_address, caller_name))

    voip_manager.on_runtime_snapshot_change(on_runtime_snapshot)

    try:
        if not voip_manager.start():
            logger.error("Failed to start VoIP manager")
            raise typer.Exit(code=1)

        logger.info(f"Waiting for incoming calls on {voip_config.sip_identity}")
        logger.info("Press Ctrl+C to exit")

        while True:
            voip_manager.iterate()
            time.sleep(max(0.01, voip_config.iterate_interval_ms / 1000.0))
    except KeyboardInterrupt:
        logger.info("Interrupted")
    finally:
        voip_manager.stop()
        logger.info(f"Total incoming calls detected: {len(incoming_calls)}")
        for address, name in incoming_calls:
            logger.info(f"  - {name} ({address})")
