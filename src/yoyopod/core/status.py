"""Runtime snapshot builders for the frozen scaffold spine."""

from __future__ import annotations

from typing import Any


def build_runtime_status(app: Any) -> dict[str, object]:
    """Return the core scaffold runtime snapshot without persistence metadata."""

    return {
        "states": {
            entity: {
                "value": _jsonify(value.value),
                "attrs": _jsonify(dict(value.attrs)),
                "last_changed_at": value.last_changed_at,
            }
            for entity, value in sorted(app.states.all().items())
        },
        "subscriptions": app.bus.subscription_counts(),
        "services": [f"{domain}.{service}" for domain, service in app.services.registered()],
        "tick_stats_last_100": app.tick_stats_snapshot(),
    }


def _jsonify(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonify(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonify(item) for item in value]
    if hasattr(value, "__dict__"):
        return {
            str(key): _jsonify(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return str(value)
