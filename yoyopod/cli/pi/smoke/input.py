"""Input-adapter smoke check helpers."""

from __future__ import annotations

import time
from typing import Any

from .types import CheckResult


def _input_check(display: object, app_config: dict[str, Any]) -> CheckResult:
    """Validate that the matching input adapter can be constructed."""
    from yoyopod.ui.input import get_input_manager

    input_manager = None

    try:
        input_manager = get_input_manager(
            display.get_adapter(),  # type: ignore[union-attr]
            config=app_config,
            simulate=False,
        )
        if input_manager is None:
            return CheckResult(
                name="input",
                status="fail",
                details="no input adapter was created for the detected display hardware",
            )

        capabilities = sorted(action.value for action in input_manager.get_capabilities())
        interaction_profile = input_manager.interaction_profile.value
        input_manager.start()
        time.sleep(0.1)
        input_manager.stop()

        return CheckResult(
            name="input",
            status="pass",
            details=(f"profile={interaction_profile}, " f"capabilities={', '.join(capabilities)}"),
        )
    except Exception as exc:
        return CheckResult(name="input", status="fail", details=str(exc))
    finally:
        if input_manager is not None:
            try:
                input_manager.stop()
            except Exception:
                pass
