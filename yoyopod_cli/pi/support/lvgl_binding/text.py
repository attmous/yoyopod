"""Text normalization helpers for the LVGL font path."""

from __future__ import annotations

_LVGL_TEXT_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201b": "'",
        "\u00b4": "'",
        "\u02bb": "'",
        "\u02bc": "'",
        "\uff07": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2011": "-",
        "\u2026": "...",
        "\u00a0": " ",
        "\u2007": " ",
        "\u202f": " ",
    }
)


def normalize_lvgl_text(value: str) -> str:
    """Replace common punctuation glyphs missing from bundled LVGL fonts."""

    return value.translate(_LVGL_TEXT_TRANSLATION)
