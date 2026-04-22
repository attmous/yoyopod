"""Typed configuration helpers and coercion primitives."""

from __future__ import annotations

import os
from dataclasses import MISSING, asdict, field, fields, is_dataclass
from pathlib import Path
from types import UnionType
from typing import Any, TypeVar, Union, get_args, get_origin, get_type_hints

import yaml

T = TypeVar("T")


def config_value(*, default: Any = MISSING, default_factory: Any = MISSING, env: str | None = None):
    """Create a dataclass field with optional environment override metadata."""

    metadata: dict[str, Any] = {}
    if env is not None:
        metadata["env"] = env

    if default is not MISSING:
        return field(default=default, metadata=metadata)
    if default_factory is not MISSING:
        return field(default_factory=default_factory, metadata=metadata)
    return field(metadata=metadata)


def load_config_model_from_yaml(model_cls: type[T], path: Path) -> T:
    """Load a typed config model from YAML with env-var overlays."""

    data: dict[str, Any] = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
            if isinstance(loaded, dict):
                data = loaded
    return build_config_model(model_cls, data)


def build_config_model(model_cls: type[T], data: dict[str, Any] | None = None) -> T:
    """Build a config dataclass from raw YAML data plus environment overrides."""

    payload = data if isinstance(data, dict) else {}
    kwargs: dict[str, Any] = {}
    type_hints = get_type_hints(model_cls)

    for model_field in fields(model_cls):
        field_type = type_hints.get(model_field.name, model_field.type)
        env_name = model_field.metadata.get("env")
        env_value = os.getenv(env_name) if env_name else None

        if env_name and env_value not in (None, ""):
            kwargs[model_field.name] = _coerce_value(env_value, field_type)
            continue

        raw_value = payload.get(model_field.name, MISSING)
        nested_type = _unwrap_optional(field_type)
        if raw_value is not MISSING:
            if _is_dataclass_type(nested_type):
                nested_payload = raw_value if isinstance(raw_value, dict) else {}
                kwargs[model_field.name] = build_config_model(nested_type, nested_payload)
            else:
                kwargs[model_field.name] = _coerce_value(raw_value, field_type)
            continue

        if _is_dataclass_type(nested_type) and model_field.default is not None:
            kwargs[model_field.name] = build_config_model(nested_type, {})
        elif model_field.default is not MISSING:
            kwargs[model_field.name] = model_field.default
        elif model_field.default_factory is not MISSING:
            kwargs[model_field.name] = model_field.default_factory()
        else:
            raise TypeError(f"Missing required config field: {model_field.name}")

    return model_cls(**kwargs)


def config_to_dict(model: Any) -> dict[str, Any]:
    """Convert a config dataclass to a plain dictionary."""

    return asdict(model)


def _unwrap_optional(field_type: Any) -> Any:
    """Return the concrete type inside an Optional/Union when possible."""

    origin = get_origin(field_type)
    if origin in (UnionType, Union):
        args = [arg for arg in get_args(field_type) if arg is not type(None)]
        if len(args) == 1:
            return args[0]
    return field_type


def _is_dataclass_type(field_type: Any) -> bool:
    """Return True when the provided type is a dataclass class."""

    return isinstance(field_type, type) and is_dataclass(field_type)


def _coerce_value(value: Any, field_type: Any) -> Any:
    """Coerce YAML/env values into the annotated field type."""

    target_type = _unwrap_optional(field_type)
    origin = get_origin(target_type)

    if target_type is Any or value is None:
        return value
    if origin in (list, dict, tuple, set):
        return value
    if target_type is bool:
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"Cannot coerce {value!r} to bool")
    if target_type is int:
        if isinstance(value, str):
            return int(value, 0)
        return int(value)
    if target_type is float:
        return float(value)
    if target_type is str:
        return str(value)
    if target_type is Path:
        return Path(value)
    return value
