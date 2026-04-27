"""Focused tests for LVGL cffi binding string buffer reuse."""

from __future__ import annotations

from collections import OrderedDict

from yoyopod.ui.lvgl_binding.binding import LvglBinding


class FakeCharArray:
    """Small identity-bearing stand-in for a cffi char array."""

    def __init__(self, value: bytes) -> None:
        self.value = value


class FakeFFI:
    """Tiny cffi double that records each buffer allocation."""

    def __init__(self) -> None:
        self.NULL = object()
        self.allocations: list[FakeCharArray] = []

    def new(self, cdecl: str, value: bytes) -> FakeCharArray:
        assert cdecl == "char[]"
        allocation = FakeCharArray(value)
        self.allocations.append(allocation)
        return allocation


class FakeLib:
    """Minimal native shim double for hub sync tests."""

    def __init__(self) -> None:
        self.hub_sync_calls: list[tuple[object, ...]] = []
        self.ask_sync_calls: list[tuple[object, ...]] = []

    def yoyopod_lvgl_hub_sync(self, *args: object) -> int:
        self.hub_sync_calls.append(args)
        return 0

    def yoyopod_lvgl_ask_sync(self, *args: object) -> int:
        self.ask_sync_calls.append(args)
        return 0


def _make_binding() -> tuple[LvglBinding, FakeFFI, FakeLib]:
    binding = LvglBinding.__new__(LvglBinding)
    ffi = FakeFFI()
    lib = FakeLib()
    binding.ffi = ffi
    binding.lib = lib
    binding._hub_sync_string_cache = OrderedDict()
    return binding, ffi, lib


def test_hub_sync_reuses_cached_char_arrays_for_static_strings() -> None:
    """Hub sync should retain static cffi buffers across refreshes."""

    binding, ffi, lib = _make_binding()

    binding.hub_sync(
        icon_key="listen",
        title="Listen",
        subtitle="",
        footer="Tap = Next | 2x Tap = Open",
        time_text="12:00",
        accent=(1, 2, 3),
        selected_index=0,
        total_cards=4,
        voip_state=1,
        battery_percent=92,
        charging=False,
        power_available=True,
    )
    binding.hub_sync(
        icon_key="listen",
        title="Listen",
        subtitle="",
        footer="Tap = Next | 2x Tap = Open",
        time_text="12:01",
        accent=(1, 2, 3),
        selected_index=1,
        total_cards=4,
        voip_state=1,
        battery_percent=92,
        charging=False,
        power_available=True,
    )

    first_call = lib.hub_sync_calls[0]
    second_call = lib.hub_sync_calls[1]

    assert first_call[0] is second_call[0]
    assert first_call[1] is second_call[1]
    assert first_call[2] is second_call[2]
    assert first_call[3] is second_call[3]
    assert first_call[4] is not second_call[4]
    assert [allocation.value for allocation in ffi.allocations] == [
        b"listen",
        b"Listen",
        b"",
        b"Tap = Next | 2x Tap = Open",
        b"12:00",
        b"12:01",
    ]


def test_hub_sync_cache_evicts_old_dynamic_entries() -> None:
    """Hub sync should keep the cache bounded when titles churn."""

    binding, _, _ = _make_binding()

    for index in range(binding.HUB_SYNC_STRING_CACHE_LIMIT - 2):
        binding.hub_sync(
            icon_key="listen",
            title=f"Title {index}",
            subtitle="",
            footer="Tap = Next | 2x Tap = Open",
            time_text=None,
            accent=(1, 2, 3),
            selected_index=index,
            total_cards=4,
            voip_state=1,
            battery_percent=92,
            charging=False,
            power_available=True,
        )

    assert len(binding._hub_sync_string_cache) == binding.HUB_SYNC_STRING_CACHE_LIMIT
    assert "Title 0" not in binding._hub_sync_string_cache
    assert f"Title {binding.HUB_SYNC_STRING_CACHE_LIMIT - 3}" in binding._hub_sync_string_cache
    assert "listen" in binding._hub_sync_string_cache
    assert "" in binding._hub_sync_string_cache
    assert "Tap = Next | 2x Tap = Open" in binding._hub_sync_string_cache


def test_ask_sync_normalizes_typographic_punctuation_for_lvgl_fonts() -> None:
    """Ask text should avoid unsupported punctuation glyphs in the LVGL font path."""

    binding, ffi, lib = _make_binding()

    binding.ask_sync(
        icon_key="ask",
        title_text="It\u2019s story time",
        subtitle_text="It\u00b4s okay to say \u201cyes\u201d.",
        footer="A ask again",
        voip_state=0,
        battery_percent=100,
        charging=False,
        power_available=True,
        accent=(1, 2, 3),
    )

    assert [allocation.value for allocation in ffi.allocations[:4]] == [
        b"ask",
        b"It's story time",
        b"It's okay to say \"yes\".",
        b"A ask again",
    ]
    assert len(lib.ask_sync_calls) == 1
