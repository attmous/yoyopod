"""VoIP smoke check helpers."""

from __future__ import annotations

from pathlib import Path
import time

from .types import CheckResult


def _voip_check(config_dir: Path, registration_timeout: float) -> CheckResult:
    """Validate Liblinphone startup and SIP registration."""
    from yoyopod.config import ConfigManager
    from yoyopod.communication import VoIPConfig, VoIPManager
    from yoyopod.communication.integrations.liblinphone import LiblinphoneBinding

    config_manager = ConfigManager(config_dir=str(config_dir))
    voip_config = VoIPConfig.from_config_manager(config_manager)
    binding = LiblinphoneBinding.try_load()
    if binding is None:
        return CheckResult(
            name="voip",
            status="fail",
            details="Liblinphone shim is unavailable; run yoyoctl build liblinphone on the Pi",
        )

    if not voip_config.sip_identity:
        return CheckResult(
            name="voip",
            status="fail",
            details="sip_identity is empty in config/communication/calling.yaml",
        )

    manager = VoIPManager(
        voip_config,
        people_directory=None,
    )
    try:
        if not manager.start():
            return CheckResult(
                name="voip",
                status="fail",
                details="VoIP manager failed to start",
            )

        deadline = time.time() + registration_timeout
        last_status = manager.get_status()

        while time.time() < deadline:
            manager.iterate()
            last_status = manager.get_status()
            if last_status["registered"]:
                return CheckResult(
                    name="voip",
                    status="pass",
                    details=(
                        f"registered={last_status['registered']}, "
                        f"state={last_status['registration_state']}, "
                        f"identity={last_status['sip_identity']}"
                    ),
                )

            if last_status["registration_state"] == "failed":
                break

            time.sleep(0.5)

        return CheckResult(
            name="voip",
            status="fail",
            details=(
                f"registration timed out or failed; "
                f"state={last_status['registration_state']}, "
                f"identity={last_status['sip_identity']}"
            ),
        )
    except Exception as exc:
        return CheckResult(name="voip", status="fail", details=str(exc))
    finally:
        manager.stop()
