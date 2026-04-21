"""Unit tests for the gpiod-based 4-button input adapter."""

from __future__ import annotations

from enum import IntEnum
from types import SimpleNamespace

import pytest

from yoyopod.ui.input.hal import InputAction


def test_adapter_capabilities():
    from yoyopod.ui.input.adapters.gpiod_buttons import GpiodButtonAdapter

    adapter = GpiodButtonAdapter(pin_config={}, simulate=True)
    caps = adapter.get_capabilities()
    assert InputAction.SELECT in caps
    assert InputAction.BACK in caps
    assert InputAction.UP in caps
    assert InputAction.DOWN in caps
    assert InputAction.HOME in caps


def test_adapter_fires_callback_on_simulate():
    from yoyopod.ui.input.adapters.gpiod_buttons import GpiodButtonAdapter

    adapter = GpiodButtonAdapter(pin_config={}, simulate=True)
    received = []
    adapter.on_action(InputAction.SELECT, lambda data: received.append(("select", data)))
    adapter._fire_action(InputAction.SELECT, {"button": "A"})
    assert len(received) == 1
    assert received[0] == ("select", {"button": "A"})


def test_clear_callbacks():
    from yoyopod.ui.input.adapters.gpiod_buttons import GpiodButtonAdapter

    adapter = GpiodButtonAdapter(pin_config={}, simulate=True)
    adapter.on_action(InputAction.SELECT, lambda data: None)
    assert len(adapter.callbacks) > 0
    adapter.clear_callbacks()
    assert len(adapter.callbacks) == 0


def test_adapter_start_stop_lifecycle():
    from yoyopod.ui.input.adapters.gpiod_buttons import GpiodButtonAdapter

    adapter = GpiodButtonAdapter(pin_config={}, simulate=True)
    adapter.start()
    assert adapter.running is True
    adapter.stop()
    assert adapter.running is False


def test_debounced_release_emits_action_without_busy_polling() -> None:
    from yoyopod.ui.input.adapters.gpiod_buttons import Button, GpiodButtonAdapter

    adapter = GpiodButtonAdapter(pin_config={}, simulate=True)
    received: list[tuple[str, dict[str, str]]] = []
    adapter.on_action(
        InputAction.SELECT,
        lambda data: received.append(("select", data)),
    )

    adapter._observe_raw_state(Button.A, True, 1.0)
    adapter._advance_button_state(Button.A, 1.06)
    adapter._observe_raw_state(Button.A, False, 1.20)
    adapter._advance_button_state(Button.A, 1.26)

    assert received == [("select", {"button": "A"})]


def test_edge_wait_loop_blocks_between_events(monkeypatch: pytest.MonkeyPatch) -> None:
    from yoyopod.ui.input.adapters import gpiod_buttons

    class FakeLine:
        def __init__(self, fd: int) -> None:
            self.fd = fd

        def get_value(self) -> int:
            return 1

        def release(self) -> None:
            return None

    class FakeChip:
        def close(self) -> None:
            return None

    line_by_offset = {
        10: FakeLine(101),
        11: FakeLine(102),
        12: FakeLine(103),
        13: FakeLine(104),
    }
    timeouts: list[float] = []

    def fake_select(reads, _writes, _errors, timeout):
        timeouts.append(timeout)
        adapter._stop_event.set()
        return ([], [], [])

    monkeypatch.setattr(gpiod_buttons, "HAS_GPIOD", True)
    monkeypatch.setattr(gpiod_buttons, "open_chip", lambda _name: FakeChip())
    monkeypatch.setattr(
        gpiod_buttons,
        "request_input_events",
        lambda _chip, line_offset, _consumer: line_by_offset[line_offset],
    )
    monkeypatch.setattr(gpiod_buttons, "get_event_fd", lambda line: line.fd)
    monkeypatch.setattr(gpiod_buttons, "read_edge_events", lambda _line: [])
    monkeypatch.setattr(gpiod_buttons.select, "select", fake_select)

    adapter = gpiod_buttons.GpiodButtonAdapter(
        pin_config={
            "button_a": {"chip": "gpiochip0", "line": 10},
            "button_b": {"chip": "gpiochip0", "line": 11},
            "button_x": {"chip": "gpiochip0", "line": 12},
            "button_y": {"chip": "gpiochip0", "line": 13},
        },
        simulate=False,
    )

    adapter._poll_loop()

    assert timeouts == [gpiod_buttons._EDGE_IDLE_WAIT_TIMEOUT]


def test_negative_event_fd_falls_back_to_polling_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yoyopod.ui.input.adapters import gpiod_buttons

    class FakeLine:
        def event_get_fd(self) -> int:
            return -1

        def get_value(self) -> int:
            return 1

        def release(self) -> None:
            return None

    class FakeChip:
        def close(self) -> None:
            return None

    line = FakeLine()
    polling_calls: list[str] = []

    def fake_select(_reads, _writes, _errors, _timeout):
        raise AssertionError("invalid GPIO event fds should never reach select()")

    monkeypatch.setattr(gpiod_buttons, "HAS_GPIOD", True)
    monkeypatch.setattr(gpiod_buttons, "open_chip", lambda _name: FakeChip())
    monkeypatch.setattr(
        gpiod_buttons,
        "request_input_events",
        lambda _chip, _line_offset, _consumer: line,
    )
    monkeypatch.setattr(gpiod_buttons.select, "select", fake_select)

    adapter = gpiod_buttons.GpiodButtonAdapter(
        pin_config={"button_a": {"chip": "gpiochip0", "line": 10}},
        simulate=False,
    )
    monkeypatch.setattr(
        adapter,
        "_polling_loop",
        lambda: polling_calls.append("polled"),
    )

    assert adapter._line_event_fds == {}

    adapter._poll_loop()

    assert polling_calls == ["polled"]


def test_edge_wait_loop_samples_level_when_event_drain_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yoyopod.ui.input.adapters import gpiod_buttons
    from yoyopod.ui.input.adapters.gpiod_buttons import Button

    class FakeLine:
        def __init__(self, fd: int, value: int) -> None:
            self.fd = fd
            self.value = value

        def get_value(self) -> int:
            return self.value

        def release(self) -> None:
            return None

    class FakeChip:
        def close(self) -> None:
            return None

    line = FakeLine(101, 0)
    clock = iter((10.0, 10.0, 10.0))

    def fake_select(reads, _writes, _errors, timeout):
        assert reads == [101]
        assert timeout > 0.0
        line.value = 1
        adapter._stop_event.set()
        return ([101], [], [])

    monkeypatch.setattr(gpiod_buttons, "HAS_GPIOD", True)
    monkeypatch.setattr(gpiod_buttons, "open_chip", lambda _name: FakeChip())
    monkeypatch.setattr(
        gpiod_buttons,
        "request_input_events",
        lambda _chip, _line_offset, _consumer: line,
    )
    monkeypatch.setattr(gpiod_buttons, "get_event_fd", lambda requested_line: requested_line.fd)
    monkeypatch.setattr(
        gpiod_buttons,
        "read_edge_events",
        lambda _line: (_ for _ in ()).throw(RuntimeError("drain failed")),
    )
    monkeypatch.setattr(gpiod_buttons.select, "select", fake_select)
    monkeypatch.setattr(gpiod_buttons.time, "monotonic", lambda: next(clock))

    adapter = gpiod_buttons.GpiodButtonAdapter(
        pin_config={"button_a": {"chip": "gpiochip0", "line": 10}},
        simulate=False,
    )
    received: list[tuple[str, dict[str, str]]] = []
    adapter.on_action(
        InputAction.SELECT,
        lambda data: received.append(("select", data)),
    )
    adapter._event_wait_loop()

    transition_started_at = adapter._transition_times[Button.A]
    assert transition_started_at == 10.0

    adapter._advance_button_state(Button.A, transition_started_at + 0.06)

    assert received == [("select", {"button": "A"})]


def test_read_edge_events_drains_legacy_event_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    import yoyopod.ui.gpiod_compat as gpiod_compat

    first = object()
    second = object()
    pending_events = [first, second]
    select_calls: list[tuple[list[int], float]] = []

    class FakeLine:
        fd = 101

        def event_read(self) -> object:
            return pending_events.pop(0)

    def fake_select(reads, _writes, _errors, timeout):
        select_calls.append((list(reads), timeout))
        return ([101], [], []) if pending_events else ([], [], [])

    monkeypatch.setattr(gpiod_compat.select, "select", fake_select)

    assert gpiod_compat.read_edge_events(FakeLine()) == [first, second]
    assert select_calls == [([101], 0.0), ([101], 0.0)]


def test_request_input_events_supports_official_gpiod_v2_request_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import yoyopod.ui.gpiod_compat as gpiod_compat

    request_calls: list[tuple[str, dict[int, object]]] = []
    inactive_token = object()
    active_token = object()

    class FakeLineSettings:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class FakeEvent:
        def __init__(self, line_offset: int) -> None:
            self.line_offset = line_offset

    class FakeRequest:
        def __init__(self) -> None:
            self.values = {7: inactive_token}

        def get_value(self, offset: int) -> object:
            return self.values[offset]

        def read_edge_events(self) -> list[FakeEvent]:
            return [FakeEvent(7), FakeEvent(99)]

        def fileno(self) -> int:
            return 321

        def release(self) -> None:
            return None

    class FakeChip:
        def request_lines(self, *, consumer: str, config: dict[int, object]) -> FakeRequest:
            request_calls.append((consumer, config))
            return FakeRequest()

        def close(self) -> None:
            return None

    fake_gpiod = SimpleNamespace(
        Chip=lambda _path: FakeChip(),
        LineSettings=FakeLineSettings,
        line=SimpleNamespace(
            Direction=SimpleNamespace(INPUT="input", OUTPUT="output"),
            Bias=SimpleNamespace(DISABLED="bias-disabled"),
            Edge=SimpleNamespace(BOTH="both-edges"),
            Value=SimpleNamespace(ACTIVE=active_token, INACTIVE=inactive_token),
        ),
    )

    monkeypatch.setattr(gpiod_compat, "HAS_GPIOD", True)
    monkeypatch.setattr(gpiod_compat, "_gpiod", fake_gpiod)

    chip = gpiod_compat.open_chip("gpiochip0")
    line = gpiod_compat.request_input_events(chip, 7, "yoyopod-btn")

    assert line.get_value() == 0
    assert gpiod_compat.get_event_fd(line) == 321
    assert [event.line_offset for event in gpiod_compat.read_edge_events(line)] == [7]

    consumer, config = request_calls[0]
    assert consumer == "yoyopod-btn"
    assert config[7].kwargs == {
        "direction": "input",
        "bias": "bias-disabled",
        "edge_detection": "both-edges",
    }


def test_request_output_supports_official_gpiod_v2_request_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import yoyopod.ui.gpiod_compat as gpiod_compat

    set_calls: list[tuple[int, object]] = []
    inactive_token = object()
    active_token = object()

    class FakeLineSettings:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class FakeRequest:
        def set_value(self, offset: int, value: object) -> None:
            set_calls.append((offset, value))

        def release(self) -> None:
            return None

    class FakeChip:
        def request_lines(self, *, consumer: str, config: dict[int, object]) -> FakeRequest:
            assert consumer == "pimoroni-led-r"
            assert config[12].kwargs == {
                "direction": "output",
                "output_value": active_token,
            }
            return FakeRequest()

        def close(self) -> None:
            return None

    fake_gpiod = SimpleNamespace(
        Chip=lambda _path: FakeChip(),
        LineSettings=FakeLineSettings,
        line=SimpleNamespace(
            Direction=SimpleNamespace(INPUT="input", OUTPUT="output"),
            Bias=SimpleNamespace(DISABLED="bias-disabled"),
            Edge=SimpleNamespace(BOTH="both-edges"),
            Value=SimpleNamespace(ACTIVE=active_token, INACTIVE=inactive_token),
        ),
    )

    monkeypatch.setattr(gpiod_compat, "HAS_GPIOD", True)
    monkeypatch.setattr(gpiod_compat, "_gpiod", fake_gpiod)

    chip = gpiod_compat.open_chip("gpiochip0")
    line = gpiod_compat.request_output(chip, 12, "pimoroni-led-r", default_val=1)
    line.set_value(0)

    assert set_calls == [(12, inactive_token)]


def test_request_output_preserves_falsey_inactive_enum_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import yoyopod.ui.gpiod_compat as gpiod_compat

    set_calls: list[tuple[int, object]] = []

    class FakeValue(IntEnum):
        INACTIVE = 0
        ACTIVE = 1

    class FakeLineSettings:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class FakeRequest:
        def set_value(self, offset: int, value: object) -> None:
            set_calls.append((offset, value))

        def release(self) -> None:
            return None

    class FakeChip:
        def request_lines(self, *, consumer: str, config: dict[int, object]) -> FakeRequest:
            assert consumer == "pimoroni-led-r"
            assert config[12].kwargs == {
                "direction": "output",
                "output_value": FakeValue.INACTIVE,
            }
            return FakeRequest()

        def close(self) -> None:
            return None

    fake_gpiod = SimpleNamespace(
        Chip=lambda _path: FakeChip(),
        LineSettings=FakeLineSettings,
        line=SimpleNamespace(
            Direction=SimpleNamespace(INPUT="input", OUTPUT="output"),
            Bias=SimpleNamespace(DISABLED="bias-disabled"),
            Edge=SimpleNamespace(BOTH="both-edges"),
            Value=FakeValue,
        ),
    )

    monkeypatch.setattr(gpiod_compat, "HAS_GPIOD", True)
    monkeypatch.setattr(gpiod_compat, "_gpiod", fake_gpiod)

    chip = gpiod_compat.open_chip("gpiochip0")
    line = gpiod_compat.request_output(chip, 12, "pimoroni-led-r", default_val=0)
    line.set_value(0)

    assert set_calls == [(12, FakeValue.INACTIVE)]


def test_request_input_events_does_not_mask_internal_type_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import yoyopod.ui.gpiod_compat as gpiod_compat

    class FakeLineSettings:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class FakeChip:
        def request_lines(self, *, consumer: str, config: dict[int, object]) -> object:
            raise TypeError("internal line request failure")

        def close(self) -> None:
            return None

    fake_gpiod = SimpleNamespace(
        Chip=lambda _path: FakeChip(),
        LineSettings=FakeLineSettings,
        line=SimpleNamespace(
            Direction=SimpleNamespace(INPUT="input", OUTPUT="output"),
            Bias=SimpleNamespace(DISABLED="bias-disabled"),
            Edge=SimpleNamespace(BOTH="both-edges"),
            Value=SimpleNamespace(ACTIVE="active", INACTIVE="inactive"),
        ),
    )

    monkeypatch.setattr(gpiod_compat, "HAS_GPIOD", True)
    monkeypatch.setattr(gpiod_compat, "_gpiod", fake_gpiod)

    chip = gpiod_compat.open_chip("gpiochip0")
    with pytest.raises(TypeError, match="internal line request failure"):
        gpiod_compat.request_input_events(chip, 7, "yoyopod-btn")


def test_request_input_events_treats_no_keyword_type_error_as_signature_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import yoyopod.ui.gpiod_compat as gpiod_compat

    request_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    class FakeLineSettings:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class FakeRequest:
        def __init__(self) -> None:
            self.values = {7: 0}

        def get_value(self, offset: int) -> int:
            return self.values[offset]

        def read_edge_events(self) -> list[object]:
            return []

        def fileno(self) -> int:
            return 321

        def release(self) -> None:
            return None

    class FakeChip:
        def close(self) -> None:
            return None

    def fake_request_lines(*args, **kwargs) -> FakeRequest:
        request_calls.append((args, kwargs))
        if kwargs:
            raise TypeError("request_lines() takes no keyword arguments")
        return FakeRequest()

    fake_gpiod = SimpleNamespace(
        Chip=lambda _path: FakeChip(),
        LineSettings=FakeLineSettings,
        request_lines=fake_request_lines,
        line=SimpleNamespace(
            Direction=SimpleNamespace(INPUT="input", OUTPUT="output"),
            Bias=SimpleNamespace(DISABLED="bias-disabled"),
            Edge=SimpleNamespace(BOTH="both-edges"),
            Value=SimpleNamespace(ACTIVE="active", INACTIVE="inactive"),
        ),
    )

    def fake_signature(_func: object) -> object:
        raise ValueError("signature unavailable")

    monkeypatch.setattr(gpiod_compat, "HAS_GPIOD", True)
    monkeypatch.setattr(gpiod_compat, "_gpiod", fake_gpiod)
    monkeypatch.setattr(gpiod_compat.inspect, "signature", fake_signature)

    chip = gpiod_compat.open_chip("gpiochip0")
    line = gpiod_compat.request_input_events(chip, 7, "yoyopod-btn")

    assert line.get_value() == 0
    config = request_calls[0][1]["config"]
    assert request_calls == [
        (("/dev/gpiochip0",), {"consumer": "yoyopod-btn", "config": config}),
        ((), {"path": "/dev/gpiochip0", "consumer": "yoyopod-btn", "config": config}),
        (("/dev/gpiochip0", "yoyopod-btn", config), {}),
    ]


def test_event_wait_loop_seeds_initial_pressed_state(monkeypatch: pytest.MonkeyPatch) -> None:
    from yoyopod.ui.input.adapters import gpiod_buttons
    from yoyopod.ui.input.adapters.gpiod_buttons import Button

    class FakeLine:
        def __init__(self, fd: int, value: int) -> None:
            self.fd = fd
            self.value = value

        def get_value(self) -> int:
            return self.value

        def release(self) -> None:
            return None

    class FakeChip:
        def close(self) -> None:
            return None

    line = FakeLine(101, 0)
    clock = iter((10.0, 10.0, 10.0))

    def fake_select(reads, _writes, _errors, timeout):
        assert reads == [101]
        assert timeout > 0.0
        adapter._stop_event.set()
        return ([], [], [])

    monkeypatch.setattr(gpiod_buttons, "HAS_GPIOD", True)
    monkeypatch.setattr(gpiod_buttons, "open_chip", lambda _name: FakeChip())
    monkeypatch.setattr(
        gpiod_buttons,
        "request_input_events",
        lambda _chip, _line_offset, _consumer: line,
    )
    monkeypatch.setattr(gpiod_buttons, "get_event_fd", lambda requested_line: requested_line.fd)
    monkeypatch.setattr(gpiod_buttons, "read_edge_events", lambda _line: [])
    monkeypatch.setattr(gpiod_buttons.select, "select", fake_select)
    monkeypatch.setattr(gpiod_buttons.time, "monotonic", lambda: next(clock))

    adapter = gpiod_buttons.GpiodButtonAdapter(
        pin_config={"button_a": {"chip": "gpiochip0", "line": 10}},
        simulate=False,
    )

    adapter._event_wait_loop()

    assert adapter._raw_button_states[Button.A] is True
    assert adapter._button_states[Button.A] is True
    assert adapter._press_times[Button.A] == 10.0


def test_apply_edge_events_preserves_queued_transitions(monkeypatch: pytest.MonkeyPatch) -> None:
    from yoyopod.ui.input.adapters.gpiod_buttons import Button, GpiodButtonAdapter

    class FakeEvent:
        def __init__(self, event_type: str, timestamp_ns: int) -> None:
            self.event_type = event_type
            self.timestamp_ns = timestamp_ns

    class FakeLine:
        def get_value(self) -> int:
            return 1

    adapter = GpiodButtonAdapter(pin_config={}, simulate=True)
    received: list[tuple[str, dict[str, str]]] = []
    adapter.on_action(
        InputAction.SELECT,
        lambda data: received.append(("select", data)),
    )

    monkeypatch.setattr(
        "yoyopod.ui.input.adapters.gpiod_buttons.read_edge_events",
        lambda _line: [
            FakeEvent("falling", 1_000_000_000),
            FakeEvent("rising", 1_060_000_000),
        ],
    )

    adapter._apply_edge_events(Button.A, FakeLine(), 1.0)
    adapter._advance_button_state(Button.A, 1.07)
    adapter._advance_button_state(Button.A, 1.12)

    assert received == [("select", {"button": "A"})]


def test_apply_edge_events_accepts_integer_edge_constants(monkeypatch: pytest.MonkeyPatch) -> None:
    from yoyopod.ui.input.adapters.gpiod_buttons import Button, GpiodButtonAdapter

    class FakeEvent:
        def __init__(self, event_type: int, timestamp_ns: int) -> None:
            self.event_type = event_type
            self.timestamp_ns = timestamp_ns

    class FakeLine:
        def get_value(self) -> int:
            raise AssertionError("edge decoding should not fall back to sampling")

    adapter = GpiodButtonAdapter(pin_config={}, simulate=True)
    received: list[tuple[str, dict[str, str]]] = []
    adapter.on_action(InputAction.SELECT, lambda data: received.append(("select", data)))

    monkeypatch.setattr(
        "yoyopod.ui.input.adapters.gpiod_buttons.read_edge_events",
        lambda _line: [
            FakeEvent(2, 1_000_000_000),
            FakeEvent(1, 1_060_000_000),
        ],
    )

    adapter._apply_edge_events(Button.A, FakeLine(), 5.0)
    adapter._advance_button_state(Button.A, 5.07)
    adapter._advance_button_state(Button.A, 5.12)

    assert received == [("select", {"button": "A"})]


def test_edge_event_observed_at_projects_datetime_order_onto_monotonic_clock() -> None:
    from datetime import datetime, timezone

    from yoyopod.ui.input.adapters.gpiod_buttons import GpiodButtonAdapter

    class FakeEvent:
        def __init__(self, timestamp: datetime) -> None:
            self.timestamp = timestamp

    adapter = GpiodButtonAdapter(pin_config={}, simulate=True)
    first = datetime(2026, 4, 18, 9, 0, 0, tzinfo=timezone.utc)
    second = datetime(2026, 4, 18, 9, 0, 0, 60_000, tzinfo=timezone.utc)
    base = adapter._edge_event_timestamp_seconds(FakeEvent(first))

    assert base is not None
    assert adapter._edge_event_observed_at(FakeEvent(first), 10.0, base) == 10.0
    assert adapter._edge_event_observed_at(FakeEvent(second), 10.0, base) == pytest.approx(10.06)
