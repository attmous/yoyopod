#!/usr/bin/env python3
"""
Manual incoming-call debug drill.
"""

import sys
import time
from loguru import logger

# Configure logger to show DEBUG level
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="DEBUG"
)

from yoyopy.connectivity import VoIPManager, VoIPConfig
from yoyopy.config import ConfigManager

def main():
    """Run verbose incoming-call debugging with raw linphone output."""
    logger.info("=" * 60)
    logger.info("Incoming Call Debug Test")
    logger.info("=" * 60)
    logger.info("This will show ALL linphonec output lines")
    logger.info("")

    # Load configuration
    config_manager = ConfigManager(config_dir="config")
    voip_config = VoIPConfig.from_config_manager(config_manager)

    # Create VoIP manager with config_manager for contact lookup
    voip_manager = VoIPManager(voip_config, config_manager=config_manager)

    # Track incoming calls
    incoming_calls = []

    def on_incoming_call(caller_address: str, caller_name: str):
        logger.success("=" * 60)
        logger.success("INCOMING CALL CALLBACK FIRED!")
        logger.success(f"  Address: {caller_address}")
        logger.success(f"  Name: {caller_name}")
        logger.success("=" * 60)
        incoming_calls.append((caller_address, caller_name))

    voip_manager.on_incoming_call(on_incoming_call)

    try:
        # Start VoIP manager
        if not voip_manager.start():
            logger.error("Failed to start VoIP manager!")
            return 1

        logger.info("VoIP manager started successfully!")
        logger.info("")
        logger.info("Waiting for incoming calls...")
        logger.info("Call this number to test: " + voip_config.sip_identity)
        logger.info("")
        logger.info("Press Ctrl+C to exit")
        logger.info("")

        # Wait for incoming calls (forever)
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("\nTest interrupted by user")
        return 0

    finally:
        # Cleanup
        logger.info("")
        logger.info("Stopping VoIP manager...")
        voip_manager.stop()
        logger.info(f"Total incoming calls detected: {len(incoming_calls)}")
        for addr, name in incoming_calls:
            logger.info(f"  - {name} ({addr})")
        logger.info("Test completed.")


if __name__ == "__main__":
    sys.exit(main())
