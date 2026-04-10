"""yoyopy/cli/pi/voip.py — VoIP diagnostic commands."""

from __future__ import annotations

import time

import typer

from yoyopy.cli.common import configure_logging

voip_app = typer.Typer(name="voip", help="VoIP diagnostic commands.", no_args_is_help=True)


@voip_app.command()
def check() -> None:
    """Run a verbose SIP registration check against the Liblinphone backend."""
    from loguru import logger

    from yoyopy.config import ConfigManager
    from yoyopy.voip import RegistrationState, VoIPConfig, VoIPManager
    from yoyopy.voip.liblinphone_binding import LiblinphoneBinding

    configure_logging(verbose=True)

    logger.info("=" * 60)
    logger.info("Liblinphone Registration Test")
    logger.info("=" * 60)

    binding = LiblinphoneBinding.try_load()
    if binding is None:
        logger.error("Liblinphone shim is unavailable. Build it first with scripts/liblinphone_build.py.")
        raise typer.Exit(code=1)

    config_manager = ConfigManager(config_dir="config")
    voip_config = VoIPConfig.from_config_manager(config_manager)

    logger.info(f"SIP Server: {voip_config.sip_server}")
    logger.info(f"SIP Username: {voip_config.sip_username}")
    logger.info(f"SIP Identity: {voip_config.sip_identity}")
    logger.info(f"Transport: {voip_config.transport}")
    logger.info(f"STUN Server: {voip_config.stun_server}")
    logger.info(f"File transfer server: {voip_config.file_transfer_server_url or 'unset'}")

    voip_manager = VoIPManager(voip_config, config_manager=config_manager)
    registration_states: list[RegistrationState] = []
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


@voip_app.command()
def debug() -> None:
    """Monitor for incoming SIP calls with verbose logging."""
    from loguru import logger

    from yoyopy.config import ConfigManager
    from yoyopy.voip import VoIPConfig, VoIPManager
    from yoyopy.voip.liblinphone_binding import LiblinphoneBinding

    configure_logging(verbose=True)

    logger.info("=" * 60)
    logger.info("Incoming Call Debug Test")
    logger.info("=" * 60)

    binding = LiblinphoneBinding.try_load()
    if binding is None:
        logger.error("Liblinphone shim is unavailable. Build it first with scripts/liblinphone_build.py.")
        raise typer.Exit(code=1)

    config_manager = ConfigManager(config_dir="config")
    voip_config = VoIPConfig.from_config_manager(config_manager)
    voip_manager = VoIPManager(voip_config, config_manager=config_manager)
    incoming_calls: list[tuple[str, str]] = []

    def on_incoming_call(caller_address: str, caller_name: str) -> None:
        logger.success("=" * 60)
        logger.success("INCOMING CALL CALLBACK FIRED")
        logger.success(f"  Address: {caller_address}")
        logger.success(f"  Name: {caller_name}")
        logger.success("=" * 60)
        incoming_calls.append((caller_address, caller_name))

    voip_manager.on_incoming_call(on_incoming_call)

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
