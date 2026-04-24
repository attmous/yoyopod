from __future__ import annotations

from pathlib import Path


BOOTSTRAP_SH = Path(__file__).resolve().parents[2] / "deploy" / "scripts" / "bootstrap_pi.sh"


def test_bootstrap_configures_service_user_and_env_before_initial_release_install() -> None:
    script = BOOTSTRAP_SH.read_text(encoding="utf-8")

    release_install_pos = script.index('echo "bootstrap: install initial release"')
    env_pos = script.index('cat > "/etc/default/yoyopod-prod"')
    user_patch_pos = script.index('grep -q "^User="')
    daemon_reload_pos = script.index("systemctl daemon-reload")

    assert env_pos < release_install_pos
    assert user_patch_pos < release_install_pos
    assert daemon_reload_pos < release_install_pos


def test_bootstrap_keeps_root_and_bin_out_of_app_user_ownership() -> None:
    script = BOOTSTRAP_SH.read_text(encoding="utf-8")

    root_owned_pos = script.index('"${ROOT}" "${ROOT}/bin"')
    app_owned_pos = script.index('"${ROOT}/releases" "${ROOT}/state"')

    assert root_owned_pos < app_owned_pos
    assert '-o "${INVOKING_USER}" -g "${INVOKING_GROUP}" \\\n    "${ROOT}"' not in script


def test_bootstrap_completion_message_does_not_trigger_command_substitution() -> None:
    script = BOOTSTRAP_SH.read_text(encoding="utf-8")
    completion_message = script.split("cat <<EOF", maxsplit=1)[1].split("\nEOF", maxsplit=1)[0]

    assert "`" not in completion_message


def test_bootstrap_uses_distinct_dev_and_prod_roots() -> None:
    script = BOOTSTRAP_SH.read_text(encoding="utf-8")

    assert 'ROOT="/opt/yoyopod-prod"' in script
    assert 'DEV_ROOT="/opt/yoyopod-dev"' in script
    assert '"${DEV_ROOT}/checkout"' in script
    assert '"${DEV_ROOT}/venv"' in script


def test_bootstrap_installs_lane_services() -> None:
    script = BOOTSTRAP_SH.read_text(encoding="utf-8")

    assert "deploy/systemd/yoyopod-prod.service" in script
    assert "deploy/systemd/yoyopod-prod-rollback.service" in script
    assert "deploy/systemd/yoyopod-dev.service" in script
    assert "systemctl enable --now yoyopod-prod.service" in script


def test_bootstrap_disables_legacy_slot_before_enabling_prod() -> None:
    script = BOOTSTRAP_SH.read_text(encoding="utf-8")

    disable_legacy_pos = script.index("systemctl disable --now yoyopod-slot.service")
    enable_prod_pos = script.index("systemctl enable --now yoyopod-prod.service")

    assert disable_legacy_pos < enable_prod_pos


def test_bootstrap_installs_prod_ota_lane_guard() -> None:
    script = BOOTSTRAP_SH.read_text(encoding="utf-8")

    assert "deploy/scripts/prod_ota_guard.sh" in script
    assert '"${ROOT}/bin/prod-ota-guard.sh"' in script


def test_bootstrap_migration_seeds_dev_checkout_from_legacy_checkout() -> None:
    script = BOOTSTRAP_SH.read_text(encoding="utf-8")

    assert '"${DEV_ROOT}/checkout"' in script
    assert 'cp -a "${OLD}/."' in script
    assert 'rm -rf "${DEV_ROOT}/checkout/.venv"' in script
