#!/usr/bin/env python3
"""
Manual VoIP registration drill.

Tests that VoIPManager can:
1. Load configuration with HA1 hash
2. Generate .linphonerc file
3. Start linphonec
4. Register with SIP server
"""

import sys
import time
from loguru import logger

# Configure logger
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="DEBUG"
)

from yoyopy.connectivity import VoIPManager, VoIPConfig, RegistrationState
from yoyopy.config import ConfigManager

def main():
    """Run a verbose SIP registration-only check."""
    logger.info("=" * 60)
    logger.info("VoIP Registration Test")
    logger.info("=" * 60)

    # Load configuration
    logger.info("Loading configuration...")
    config_manager = ConfigManager(config_dir="config")

    # Create VoIP config
    logger.info("Creating VoIP configuration...")
    voip_config = VoIPConfig.from_config_manager(config_manager)

    # Log configuration (mask password)
    logger.info(f"SIP Server: {voip_config.sip_server}")
    logger.info(f"SIP Username: {voip_config.sip_username}")
    logger.info(f"SIP Identity: {voip_config.sip_identity}")
    logger.info(f"Transport: {voip_config.transport}")
    logger.info(f"STUN Server: {voip_config.stun_server}")
    logger.info(f"HA1 Hash: {voip_config.sip_password_ha1[:16]}... (masked)")

    # Create VoIP manager
    logger.info("")
    logger.info("Initializing VoIP manager...")
    voip_manager = VoIPManager(voip_config)

    # Track registration state changes
    registration_states = []

    def on_registration_change(state: RegistrationState):
        logger.info(f"  Registration state changed: {state.value}")
        registration_states.append(state)

    voip_manager.on_registration_change(on_registration_change)

    try:
        # Start VoIP manager
        logger.info("")
        logger.info("Starting VoIP manager...")
        if not voip_manager.start():
            logger.error("Failed to start VoIP manager!")
            return 1

        logger.info("VoIP manager started successfully!")
        logger.info("")

        # Wait for registration (max 10 seconds)
        logger.info("Waiting for registration (max 10 seconds)...")
        start_time = time.time()
        while time.time() - start_time < 10:
            status = voip_manager.get_status()

            if status['registered']:
                logger.success("")
                logger.success("=" * 60)
                logger.success("REGISTRATION SUCCESSFUL!")
                logger.success("=" * 60)
                logger.success(f"SIP Identity: {status['sip_identity']}")
                logger.success(f"Registration State: {status['registration_state']}")
                logger.success(f"Registration history: {[s.value for s in registration_states]}")
                logger.success("")

                # Keep running for a bit to verify stability
                logger.info("Keeping connection alive for 5 seconds...")
                time.sleep(5)

                return 0

            time.sleep(0.5)

        # Registration failed
        status = voip_manager.get_status()
        logger.error("")
        logger.error("=" * 60)
        logger.error("REGISTRATION FAILED!")
        logger.error("=" * 60)
        logger.error(f"Registration State: {status['registration_state']}")
        logger.error(f"Registered: {status['registered']}")
        logger.error(f"Registration history: {[s.value for s in registration_states]}")
        logger.error("")
        logger.error("Check:")
        logger.error("  1. SIP credentials are correct in config/voip_config.yaml")
        logger.error("  2. HA1 hash matches the password")
        logger.error("  3. Network connection is working")
        logger.error("  4. SIP server is accessible")

        return 1

    except KeyboardInterrupt:
        logger.info("\nTest interrupted by user")
        return 1

    finally:
        # Cleanup
        logger.info("")
        logger.info("Stopping VoIP manager...")
        voip_manager.stop()
        logger.info("Test completed.")


if __name__ == "__main__":
    sys.exit(main())
