"""Focused tests for extracted theme text helpers."""

from yoyopod.ui.screens.theme_text import text_fit, wrap_text


class _FakeDisplay:
    def get_text_size(self, text: str, font_size: int) -> tuple[int, int]:
        return (len(text) * (font_size // 2), font_size)


def test_text_fit_truncates_with_ellipsis() -> None:
    """Theme text fitting should shorten overlong labels predictably."""

    display = _FakeDisplay()

    assert text_fit(display, "Long headline", 24, 8).endswith("...")


def test_wrap_text_limits_line_count_and_preserves_order() -> None:
    """Wrapped theme text should remain in reading order and cap the line count."""

    display = _FakeDisplay()

    lines = wrap_text(display, "one two three four five", 24, 8, max_lines=2)

    assert len(lines) == 2
    assert lines[0].startswith("one")
