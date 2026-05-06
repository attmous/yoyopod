"""
GPIOD compatibility shim used by the Whisplay driver.
"""

from __future__ import annotations

from types import ModuleType


def _normalize_gpiochip_path(candidate: object) -> object:
    """Normalize bare ``gpiochipN`` names to ``/dev/gpiochipN`` when needed."""

    if isinstance(candidate, str) and candidate.startswith("gpiochip"):
        return f"/dev/{candidate}"
    return candidate


def _patch_vendor_gpiod_compat(whisplay_module: ModuleType) -> None:
    """Normalize the WhisPlay driver's expected gpiod API for Python 3.12 envs."""

    gpiod = getattr(whisplay_module, "gpiod", None)
    if gpiod is None or getattr(gpiod, "_yoyopod_whisplay_compat", False):
        return

    line_request = getattr(gpiod, "line_request", None)
    if line_request is not None:
        aliases = {
            "LINE_REQ_DIR_OUT": "DIRECTION_OUTPUT",
            "LINE_REQ_DIR_IN": "DIRECTION_INPUT",
            "LINE_REQ_FLAG_BIAS_DISABLE": "FLAG_BIAS_DISABLE",
        }
        for alias, source_name in aliases.items():
            if not hasattr(gpiod, alias) and hasattr(line_request, source_name):
                setattr(gpiod, alias, getattr(line_request, source_name))

    if hasattr(gpiod, "chip") and not hasattr(gpiod, "Chip"):

        class _CompatLine:
            def __init__(self, line: object) -> None:
                self._line = line

            def request(self, *args, **kwargs):
                if kwargs:
                    request_config = line_request()
                    request_config.consumer = kwargs.pop("consumer", "")
                    request_config.request_type = kwargs.pop("type")
                    request_config.flags = kwargs.pop("flags", 0)
                    default_val = kwargs.pop("default_val", 0)
                    if kwargs:
                        unexpected = ", ".join(sorted(kwargs))
                        raise TypeError(f"Unexpected line.request kwargs: {unexpected}")
                    return self._line.request(request_config, default_val)
                return self._line.request(*args)

            def __getattr__(self, name: str) -> object:
                return getattr(self._line, name)

        class _CompatChip:
            def __init__(self, chip: object) -> None:
                self._chip = chip

            def get_line(self, offset: int) -> _CompatLine:
                return _CompatLine(self._chip.get_line(offset))

            def __getattr__(self, name: str) -> object:
                return getattr(self._chip, name)

        def _compat_chip(name: object):
            return _CompatChip(gpiod.chip(_normalize_gpiochip_path(name)))

        gpiod.Chip = _compat_chip
    elif hasattr(gpiod, "Chip"):
        original_chip = gpiod.Chip

        def _compat_chip(name: object):
            try:
                return original_chip(name)
            except FileNotFoundError:
                normalized = _normalize_gpiochip_path(name)
                if normalized == name:
                    raise
                return original_chip(normalized)

        gpiod.Chip = _compat_chip

    gpiod._yoyopod_whisplay_compat = True
