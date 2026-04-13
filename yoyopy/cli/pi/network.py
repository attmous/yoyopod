"""yoyopy/cli/pi/network.py — SIM7600 modem and GPS commands."""

from __future__ import annotations

from typing import Annotated

import typer

from yoyopy.cli.common import configure_logging, resolve_config_dir

network_app = typer.Typer(name="network", help="SIM7600 modem and GPS commands.", no_args_is_help=True)


@network_app.command()
def probe(
    config_dir: Annotated[str, typer.Option("--config-dir", help="Configuration directory.")] = "config",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Check if the SIM7600 modem responds to AT commands."""
    from loguru import logger

    from yoyopy.config import ConfigManager
    from yoyopy.network import NetworkManager

    configure_logging(verbose)
    config_path = resolve_config_dir(config_dir)
    config_manager = ConfigManager(config_dir=str(config_path))
    manager = NetworkManager.from_config_manager(config_manager)

    if not manager.config.enabled:
        logger.error("network module disabled in yoyopod_config.yaml")
        raise typer.Exit(code=1)

    from yoyopy.network.transport import SerialTransport, TransportError

    transport = SerialTransport(
        port=manager.config.serial_port,
        baud_rate=manager.config.baud_rate,
    )
    try:
        transport.open()
        from yoyopy.network.at_commands import AtCommandSet

        at = AtCommandSet(transport)
        if at.ping():
            print("Modem OK")
        else:
            print("Modem did not respond")
            raise typer.Exit(code=1)
    except TransportError as exc:
        logger.error(str(exc))
        raise typer.Exit(code=1)
    finally:
        transport.close()


@network_app.command()
def status(
    config_dir: Annotated[str, typer.Option("--config-dir", help="Configuration directory.")] = "config",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Show modem status: signal, carrier, registration, PPP state."""
    from loguru import logger

    from yoyopy.config import ConfigManager
    from yoyopy.network import NetworkManager
    from yoyopy.network.backend import Sim7600Backend

    configure_logging(verbose)
    config_path = resolve_config_dir(config_dir)
    config_manager = ConfigManager(config_dir=str(config_path))
    manager = NetworkManager.from_config_manager(config_manager)

    if not manager.config.enabled:
        logger.error("network module disabled in yoyopod_config.yaml")
        raise typer.Exit(code=1)

    backend = Sim7600Backend(manager.config)
    try:
        backend.open()
        backend.init_modem()
        state = backend.get_state()

        print("")
        print("SIM7600 Modem Status")
        print("====================")
        lines = [
            f"phase={state.phase.value}",
            f"sim_ready={state.sim_ready}",
            f"carrier={state.carrier or 'unknown'}",
            f"network_type={state.network_type or 'unknown'}",
            f"signal_csq={state.signal.csq if state.signal else 'unknown'}",
            f"signal_bars={state.signal.bars if state.signal else 'unknown'}",
            f"error={state.error or 'none'}",
        ]
        for line in lines:
            print(line)
    except Exception as exc:
        logger.error(f"Modem status failed: {exc}")
        raise typer.Exit(code=1)
    finally:
        backend.close()


@network_app.command()
def gps(
    config_dir: Annotated[str, typer.Option("--config-dir", help="Configuration directory.")] = "config",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Query current GPS coordinates."""
    from loguru import logger

    from yoyopy.config import ConfigManager
    from yoyopy.network import NetworkManager
    from yoyopy.network.backend import Sim7600Backend

    configure_logging(verbose)
    config_path = resolve_config_dir(config_dir)
    config_manager = ConfigManager(config_dir=str(config_path))
    manager = NetworkManager.from_config_manager(config_manager)

    if not manager.config.enabled:
        logger.error("network module disabled in yoyopod_config.yaml")
        raise typer.Exit(code=1)

    backend = Sim7600Backend(manager.config)
    try:
        backend.open()
        backend.init_modem()
        coord = backend.query_gps()

        if coord is None:
            print("No GPS fix available")
            raise typer.Exit(code=1)

        print("")
        print("GPS Coordinates")
        print("===============")
        print(f"lat={coord.lat}")
        print(f"lng={coord.lng}")
        print(f"altitude={coord.altitude}")
        print(f"speed={coord.speed}")
    except Exception as exc:
        logger.error(f"GPS query failed: {exc}")
        raise typer.Exit(code=1)
    finally:
        backend.close()
