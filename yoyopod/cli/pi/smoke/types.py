"""Shared smoke-check result value objects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CheckResult:
    """Result for one smoke-validation step."""

    name: str
    status: str
    details: str
