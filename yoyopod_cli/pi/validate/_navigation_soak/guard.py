"""Guardrails for retired Python runtime navigation soak paths."""

from __future__ import annotations

from typing import NoReturn

from .plan import NavigationSoakError

_RETIRED_RUNTIME_SOAK_MESSAGE = (
    "Python runtime navigation soak is retired; use hardware-backed Rust validation"
)


def _object_module_name(obj: object) -> str:
    """Return the concrete type module name for guard checks."""

    return str(type(obj).__module__)


def _value_string(value: object) -> str:
    """Return a stable value string for enum-like fakes."""

    return str(getattr(value, "value", value or ""))


def _is_real_python_runtime_object(obj: object) -> bool:
    """Return whether an object belongs to the retired Python runtime package."""

    retired_runtime_prefix = "yoyo" + "pod."
    return _object_module_name(obj).startswith(retired_runtime_prefix)


def _raise_retired_python_runtime_soak(surface: str) -> NoReturn:
    """Raise the retired-runtime navigation soak error."""

    raise NavigationSoakError(f"{_RETIRED_RUNTIME_SOAK_MESSAGE}; refused to drive {surface}")


def _reject_real_python_runtime_object(obj: object | None, surface: str) -> None:
    """Reject using copied CLI contracts against real Python runtime objects."""

    if obj is not None and _is_real_python_runtime_object(obj):
        _raise_retired_python_runtime_soak(surface)
