from __future__ import annotations

from pathlib import Path


ROLLBACK_SH = Path(__file__).resolve().parents[2] / "deploy" / "scripts" / "rollback.sh"


def test_rollback_loads_prod_env_before_defaulting_service_name() -> None:
    script = ROLLBACK_SH.read_text(encoding="utf-8")

    load_env_pos = script.index(". /etc/default/yoyopod-prod")
    service_default_pos = script.index(
        'SERVICE_NAME="${YOYOPOD_SERVICE_NAME:-yoyopod-prod.service}"'
    )

    assert load_env_pos < service_default_pos
