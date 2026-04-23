from __future__ import annotations

from pathlib import Path


CI_YML = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def test_slot_arm64_change_detector_matches_python_release_builder() -> None:
    workflow = CI_YML.read_text(encoding="utf-8")

    assert "build_release\\.py" in workflow
    assert "scripts/(build_release|build_slot_artifact_ci)\\.sh" not in workflow
