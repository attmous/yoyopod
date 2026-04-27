"""Shared helpers for the pi_validate subpackage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from yoyopod_cli.common import REPO_ROOT

if TYPE_CHECKING:
    from yoyopod.config import MediaConfig

# ---------------------------------------------------------------------------
# Shared result type for the flattened validation suite
# ---------------------------------------------------------------------------


@dataclass
class _CheckResult:
    """Result for one validation step."""

    name: str
    status: str
    details: str


def _print_summary(name: str, results: list[_CheckResult]) -> None:
    """Print a compact summary table for one validation command."""
    print("")
    print(f"YoYoPod target validation summary: {name}")
    print("=" * 48)
    for result in results:
        print(f"[{result.status.upper():4}] {result.name}: {result.details}")


# ---------------------------------------------------------------------------
# Deploy helpers for the flattened validation suite
# ---------------------------------------------------------------------------


def _resolve_runtime_path(path_value: str) -> Path:
    """Resolve one repo-relative or absolute runtime path."""
    path = Path(path_value)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def _nearest_existing_parent(path: Path) -> Path:
    """Return the nearest existing parent for one path."""
    candidate = path if path.exists() and path.is_dir() else path.parent
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


# ---------------------------------------------------------------------------
# Smoke helpers for the flattened validation suite
# ---------------------------------------------------------------------------


def _load_app_config(config_dir: Path) -> dict[str, Any]:
    """Load the composed app config if present."""
    from loguru import logger

    from yoyopod.config import config_to_dict, load_composed_app_settings

    if not any(
        path.exists()
        for path in (
            config_dir / "app" / "core.yaml",
            config_dir / "device" / "hardware.yaml",
        )
    ):
        logger.warning("Composed app config not found under {}", config_dir)
    return cast(dict[str, Any], config_to_dict(load_composed_app_settings(config_dir)))


def _load_media_config(config_dir: Path) -> MediaConfig:
    """Load the typed composed media config if present."""
    from yoyopod.config import ConfigManager

    return ConfigManager(config_dir=str(config_dir)).get_media_settings()
