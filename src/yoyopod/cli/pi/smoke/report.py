"""Smoke-suite report helpers."""

from __future__ import annotations

from .types import CheckResult


def _print_summary(results: list[CheckResult]) -> None:
    """Print a compact summary table."""
    print("")
    print("YoyoPod Raspberry Pi smoke summary")
    print("=" * 40)
    for result in results:
        print(f"[{result.status.upper():4}] {result.name}: {result.details}")
