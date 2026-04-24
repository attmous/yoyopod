from __future__ import annotations

from pathlib import Path


GUARD_SH = Path(__file__).resolve().parents[2] / "deploy" / "scripts" / "prod_ota_guard.sh"


def test_prod_ota_guard_refuses_to_run_when_dev_lane_is_active() -> None:
    script = GUARD_SH.read_text(encoding="utf-8")

    assert "yoyopod-dev.service" in script
    assert "dev lane is active" in script
    assert "exit 75" in script


def test_prod_ota_guard_requires_prod_lane_to_be_active() -> None:
    script = GUARD_SH.read_text(encoding="utf-8")

    assert "yoyopod-prod.service" in script
    assert "prod lane is not active" in script


def test_prod_ota_guard_loads_prod_env_before_defaulting_service_name() -> None:
    script = GUARD_SH.read_text(encoding="utf-8")

    load_env_pos = script.index(". /etc/default/yoyopod-prod")
    service_default_pos = script.index(
        'PROD_SERVICE="${YOYOPOD_SERVICE_NAME:-yoyopod-prod.service}"'
    )

    assert load_env_pos < service_default_pos
