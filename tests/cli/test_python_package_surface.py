from __future__ import annotations

from pathlib import Path

import tomllib


REPO_ROOT = Path(__file__).resolve().parents[2]


def _pyproject() -> dict[str, object]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_wheel_packages_only_cli_package() -> None:
    pyproject = _pyproject()
    wheel = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]

    assert wheel["packages"] == ["yoyopod_cli"]


def test_sdist_does_not_include_retired_python_runtime() -> None:
    pyproject = _pyproject()
    sdist = pyproject["tool"]["hatch"]["build"]["targets"]["sdist"]
    retired_package = "/" + "yoyopod"
    retired_entrypoint = retired_package + ".py"

    assert retired_package not in sdist["include"]
    assert retired_entrypoint not in sdist["include"]
    assert "/legacy" not in sdist["include"]


def test_quality_audit_types_cli_package_not_retired_runtime() -> None:
    pyproject = _pyproject()
    quality = pyproject["tool"]["yoyopod_quality"]

    assert quality["audit_type_paths"] == ["yoyopod_cli"]
