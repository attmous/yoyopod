from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_PI_SH = REPO_ROOT / "deploy" / "scripts" / "install_pi.sh"


def test_install_pi_script_is_curl_friendly_source_installer() -> None:
    script = INSTALL_PI_SH.read_text(encoding="utf-8")

    assert "set -euo pipefail" in script
    assert "YOYOPOD_INSTALL_REPO" in script
    assert "YOYOPOD_INSTALL_REF" in script
    assert "YOYOPOD_INSTALL_SOURCE_URL" in script
    assert "https://codeload.github.com/${REPO}/tar.gz/${REF}" in script
    assert "curl -fsSL" in script
    assert "mktemp -d" in script
    assert "trap cleanup EXIT" in script
    assert "tar -xzf" in script
    assert 'bootstrap="${source_dir}/deploy/scripts/bootstrap_pi.sh"' in script
    assert '"${bootstrap}" "$@"' in script


def test_install_pi_script_exposes_professional_curl_command() -> None:
    script = INSTALL_PI_SH.read_text(encoding="utf-8")

    assert "curl -fsSL" in script
    assert "sudo -E bash -s --" in script
    assert "/deploy/scripts/install_pi.sh" in script


def test_active_docs_use_curl_installer_not_manual_temp_checkout() -> None:
    active_docs = [
        REPO_ROOT / "AGENTS.md",
        REPO_ROOT / "docs" / "operations" / "DEV_PROD_LANES.md",
        REPO_ROOT / "docs" / "operations" / "SLOT_DEPLOY.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in active_docs)

    assert "curl -fsSL" in combined
    assert "install_pi.sh" in combined
    assert "temporary checkout" not in combined.lower()
    assert "/tmp/yoyopod-bootstrap" not in combined
    assert "git clone <repo-url> /tmp" not in combined
    assert "cd ~/yoyopod-core" not in combined


def test_readme_describes_lane_based_pi_bringup() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "Fresh Raspberry Pi Install" in readme
    assert "Local Developer Setup" in readme
    assert "Hardware Validation" in readme
    assert "curl -fsSL" in readme
    assert "install_pi.sh" in readme
    assert "remote mode activate dev" in readme
    assert "remote release status" in readme
    assert "Typical bring-up flow" not in readme
    assert "Basic hardware validation" not in readme
    assert "yoyopod pi validate smoke" not in readme


def test_repo_skills_describe_current_lane_contract() -> None:
    skill_files = sorted((REPO_ROOT / "skills").glob("*/SKILL.md"))
    combined = "\n".join(path.read_text(encoding="utf-8") for path in skill_files)
    combined_lower = combined.lower()

    assert "/opt/yoyopod-dev/checkout" in combined
    assert "/opt/yoyopod-prod" in combined
    assert "remote mode status" in combined
    assert "remote release install-url" in combined
    assert "bootstrap_pi.sh" not in combined
    assert "classic flow" not in combined_lower
    assert "until all pis" not in combined_lower
    assert "remote service" not in combined
