from __future__ import annotations

from pathlib import Path


BOOTSTRAP_SH = Path(__file__).resolve().parents[2] / "deploy" / "scripts" / "bootstrap_pi.sh"


def test_bootstrap_configures_service_user_and_env_before_initial_release_install() -> None:
    script = BOOTSTRAP_SH.read_text(encoding="utf-8")

    release_install_pos = script.index('echo "bootstrap: install initial release"')
    env_pos = script.index('cat > "/etc/default/yoyopod-slot"')
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
