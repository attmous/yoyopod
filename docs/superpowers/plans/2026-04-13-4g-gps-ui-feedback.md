# 4G/GPS UI Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add signal bars, GPS indicator to the status bar, and Network/GPS pages to the Setup screen.

**Architecture:** Extend the existing `render_status_bar()` in `theme.py` with two new indicators drawn before the VoIP dot. Add two `PowerPage` entries to `build_pages()` in `power.py`, backed by `NetworkManager.modem_state`. Add `gps_has_fix` to `AppContext`.

**Tech Stack:** Python 3.12+, existing Display HAL drawing primitives, pytest

---

## File Structure

### Modified Files

| File | Change |
|---|---|
| `yoyopy/app_context.py` | Add `gps_has_fix` field, extend `update_network_status()` |
| `yoyopy/ui/screens/theme.py` | Add signal bars and GPS dot to `render_status_bar()` |
| `yoyopy/ui/screens/system/power.py` | Add `network_manager` to `__init__`, add Network and GPS pages to `build_pages()` |
| `yoyopy/app.py` | Pass `network_manager` to `PowerScreen`, subscribe to GPS events |
| `tests/test_network_models.py` | Add test for `gps_has_fix` in `update_network_status()` |

---

## Task 1: AppContext gps_has_fix field

**Files:**
- Modify: `yoyopy/app_context.py`
- Modify: `tests/test_network_models.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_network_models.py`:

```python
def test_app_context_update_network_status_with_gps():
    """update_network_status should set gps_has_fix."""
    ctx = AppContext()
    assert ctx.gps_has_fix is False

    ctx.update_network_status(gps_has_fix=True)
    assert ctx.gps_has_fix is True

    ctx.update_network_status(gps_has_fix=False)
    assert ctx.gps_has_fix is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_network_models.py::test_app_context_update_network_status_with_gps -v`
Expected: FAIL with `AttributeError: 'AppContext' object has no attribute 'gps_has_fix'`

- [ ] **Step 3: Add gps_has_fix to AppContext**

In `yoyopy/app_context.py`, in the `__init__` method, after line 154 (`self.connection_type: str = "none"`), add:

```python
        self.gps_has_fix: bool = False
```

In the `update_network_status` method, extend the signature and body. The current method (around line 398) looks like:

```python
    def update_network_status(
        self,
        *,
        signal_bars: int | None = None,
        connection_type: str | None = None,
        connected: bool | None = None,
    ) -> None:
```

Change it to:

```python
    def update_network_status(
        self,
        *,
        signal_bars: int | None = None,
        connection_type: str | None = None,
        connected: bool | None = None,
        gps_has_fix: bool | None = None,
    ) -> None:
        """Update cached network telemetry from the modem backend."""
        if signal_bars is not None:
            self.signal_strength = max(0, min(4, signal_bars))
        if connection_type is not None:
            self.connection_type = connection_type
        if connected is not None:
            self.is_connected = connected
        if gps_has_fix is not None:
            self.gps_has_fix = gps_has_fix
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_network_models.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add yoyopy/app_context.py tests/test_network_models.py
git commit -m "feat(ui): add gps_has_fix to AppContext"
```

---

## Task 2: Status bar signal bars and GPS indicator

**Files:**
- Modify: `yoyopy/ui/screens/theme.py`

- [ ] **Step 1: Add signal bar and GPS rendering constants**

In `yoyopy/ui/screens/theme.py`, after the existing status bar constants (around line 42), add:

```python
STATUS_SIGNAL_BAR_WIDTH = 3
STATUS_SIGNAL_BAR_GAP = 1
STATUS_SIGNAL_BAR_HEIGHTS = (4, 7, 10, 13)
STATUS_SIGNAL_GPS_GAP = 6
STATUS_GPS_RADIUS = 3
STATUS_NETWORK_VOIP_GAP = 8
```

- [ ] **Step 2: Add signal bars rendering before VoIP dot**

In `render_status_bar()`, the current code draws the VoIP dot first at `side_inset + 3`. We need to insert signal and GPS rendering before it, shifting the VoIP dot right.

Replace the section starting from `dot_y = ...` through the VoIP dot rendering (around lines 313-321) with:

```python
    dot_y = (bar_height // 2) + (2 if is_portrait else 1)
    cursor_x = side_inset

    # -- Signal bars (only when network module is enabled) --
    network_enabled = context is not None and context.connection_type != "none" or (
        context is not None and hasattr(context, "gps_has_fix")
    )
    if context is not None and context.connection_type != "none":
        signal = context.signal_strength if context is not None else 0
        connected = context.is_connected if context is not None else False
        bar_base_y = dot_y + 3  # bottom of tallest bar aligns with dot center + offset
        for i, h in enumerate(STATUS_SIGNAL_BAR_HEIGHTS):
            bx = cursor_x + i * (STATUS_SIGNAL_BAR_WIDTH + STATUS_SIGNAL_BAR_GAP)
            by = bar_base_y - h
            if i < signal:
                if connected:
                    bar_color = SUCCESS
                else:
                    bar_color = MUTED
            else:
                bar_color = (60, 63, 70)  # dark unfilled
            display.rectangle(bx, by, bx + STATUS_SIGNAL_BAR_WIDTH, bar_base_y, fill=bar_color)
        cursor_x += 4 * (STATUS_SIGNAL_BAR_WIDTH + STATUS_SIGNAL_BAR_GAP) + STATUS_SIGNAL_GPS_GAP

    # -- GPS indicator (only when network is active) --
    if context is not None and context.connection_type != "none":
        gps_fix = context.gps_has_fix if hasattr(context, "gps_has_fix") else False
        gps_color = SUCCESS if gps_fix else MUTED
        display.circle(cursor_x + STATUS_GPS_RADIUS, dot_y, STATUS_GPS_RADIUS, fill=gps_color)
        cursor_x += STATUS_GPS_RADIUS * 2 + STATUS_NETWORK_VOIP_GAP

    # -- VoIP indicator --
    voip_state = _voip_state(context)
    time_x = cursor_x
    if voip_state != "none":
        dot_x = cursor_x + 3
        display.circle(dot_x, dot_y, 3, fill=SUCCESS if voip_state == "ready" else ERROR)
        time_x += voip_gap
```

Note: The `time_x` variable was previously computed from `side_inset`. Now it flows from `cursor_x` which accumulates the width of signal bars + GPS + VoIP. The rest of the function (time rendering, battery rendering) is unchanged.

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -q`
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add yoyopy/ui/screens/theme.py
git commit -m "feat(ui): add signal bars and GPS indicator to status bar"
```

---

## Task 3: Network and GPS Setup pages

**Files:**
- Modify: `yoyopy/ui/screens/system/power.py`

- [ ] **Step 1: Add network_manager parameter to PowerScreen.__init__**

In `yoyopy/ui/screens/system/power.py`, modify the `__init__` signature (line 43) to add `network_manager` after `power_manager`:

```python
    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        *,
        power_manager: Optional["PowerManager"] = None,
        network_manager: Optional[object] = None,
        status_provider: Optional[Callable[[], dict[str, object]]] = None,
        volume_up_action: Optional[Callable[[int], int | None]] = None,
        volume_down_action: Optional[Callable[[int], int | None]] = None,
        mute_action: Optional[Callable[[], bool]] = None,
        unmute_action: Optional[Callable[[], bool]] = None,
    ) -> None:
        super().__init__(display, context, "PowerStatus")
        self.power_manager = power_manager
        self.network_manager = network_manager
        self.status_provider = status_provider or (lambda: {})
```

- [ ] **Step 2: Add _build_network_rows method**

Add after `_build_voice_rows` (around line 271):

```python
    def _build_network_rows(self) -> list[tuple[str, str]]:
        """Build the cellular network status page."""
        if self.network_manager is None:
            return [("Status", "Disabled")]

        if not self.network_manager.config.enabled:
            return [("Status", "Disabled")]

        state = self.network_manager.modem_state
        from yoyopy.network.models import ModemPhase

        if state.phase == ModemPhase.ONLINE:
            status_text = "Online"
        elif state.phase in (ModemPhase.REGISTERED, ModemPhase.PPP_STARTING, ModemPhase.PPP_STOPPING):
            status_text = "Registered"
        elif state.phase in (ModemPhase.PROBING, ModemPhase.READY, ModemPhase.REGISTERING):
            status_text = "Connecting"
        else:
            status_text = "Offline"

        rows: list[tuple[str, str]] = [
            ("Status", status_text),
            ("Carrier", state.carrier or "Unknown"),
            ("Type", state.network_type or "Unknown"),
            ("Signal", f"{state.signal.bars}/4" if state.signal else "Unknown"),
            ("PPP", "Up" if state.phase == ModemPhase.ONLINE else "Down"),
        ]
        return rows
```

- [ ] **Step 3: Add _build_gps_rows method**

Add after `_build_network_rows`:

```python
    def _build_gps_rows(self) -> list[tuple[str, str]]:
        """Build the GPS status page."""
        if self.network_manager is None or not self.network_manager.config.enabled:
            return [("Fix", "Disabled"), ("Lat", "--"), ("Lng", "--"), ("Alt", "--"), ("Speed", "--")]

        if not self.network_manager.config.gps_enabled:
            return [("Fix", "Disabled"), ("Lat", "--"), ("Lng", "--"), ("Alt", "--"), ("Speed", "--")]

        state = self.network_manager.modem_state
        if state.gps is None:
            return [("Fix", "No"), ("Lat", "--"), ("Lng", "--"), ("Alt", "--"), ("Speed", "--")]

        coord = state.gps
        return [
            ("Fix", "Yes"),
            ("Lat", f"{coord.lat:.6f}"),
            ("Lng", f"{coord.lng:.6f}"),
            ("Alt", f"{coord.altitude:.1f}m"),
            ("Speed", f"{coord.speed:.1f}km/h"),
        ]
```

- [ ] **Step 4: Insert Network and GPS pages into build_pages**

Modify the `build_pages` method (line 235). Change the return statement from:

```python
        return [
            PowerPage(title="Power", rows=battery_rows[:4]),
            PowerPage(title="Time", rows=battery_rows[4:6] + runtime_rows[:2]),
            PowerPage(title="Care", rows=runtime_rows[2:]),
            PowerPage(title="Voice", rows=self._build_voice_rows(), interactive=True),
        ]
```

To:

```python
        pages = [
            PowerPage(title="Power", rows=battery_rows[:4]),
        ]

        if self.network_manager is not None and self.network_manager.config.enabled:
            pages.append(PowerPage(title="Network", rows=self._build_network_rows()))
            pages.append(PowerPage(title="GPS", rows=self._build_gps_rows()))

        pages.extend([
            PowerPage(title="Time", rows=battery_rows[4:6] + runtime_rows[:2]),
            PowerPage(title="Care", rows=runtime_rows[2:]),
            PowerPage(title="Voice", rows=self._build_voice_rows(), interactive=True),
        ])
        return pages
```

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -q`
Expected: all tests pass (existing PowerScreen tests should still pass since network_manager defaults to None, which means Network/GPS pages are not added)

- [ ] **Step 6: Commit**

```bash
git add yoyopy/ui/screens/system/power.py
git commit -m "feat(ui): add Network and GPS pages to Setup screen"
```

---

## Task 4: Wire network_manager into PowerScreen and subscribe to GPS events

**Files:**
- Modify: `yoyopy/app.py`

- [ ] **Step 1: Pass network_manager to PowerScreen constructor**

In `yoyopy/app.py`, find where `PowerScreen` is constructed (in `_setup_screens`). It currently looks like:

```python
self.power_screen = PowerScreen(
    self.display,
    self.context,
    power_manager=self.power_manager,
    status_provider=...,
)
```

Add `network_manager=self.network_manager` to the constructor call:

```python
self.power_screen = PowerScreen(
    self.display,
    self.context,
    power_manager=self.power_manager,
    network_manager=self.network_manager,
    status_provider=...,
)
```

- [ ] **Step 2: Subscribe to NetworkGpsFixEvent to update gps_has_fix**

In the imports section of `app.py`, ensure `NetworkGpsFixEvent` is imported. It should already be available via `yoyopy/events.py`.

Add to the imports alongside the existing `NetworkPppUpEvent`:

```python
from yoyopy.events import NetworkPppUpEvent, NetworkGpsFixEvent
```

In `__init__`, add a subscription after the existing `NetworkPppUpEvent` subscription:

```python
self.event_bus.subscribe(NetworkGpsFixEvent, self._handle_network_gps_fix)
```

Add the handler method:

```python
def _handle_network_gps_fix(self, event: "NetworkGpsFixEvent") -> None:
    """Update GPS fix state in AppContext."""
    if self.context:
        self.context.update_network_status(gps_has_fix=True)
```

- [ ] **Step 3: Update the PPP up handler to also set signal bars**

The existing `_handle_network_ppp_up` method should also be setting signal from the modem state. Update it:

```python
def _handle_network_ppp_up(self, event: "NetworkPppUpEvent") -> None:
    """Update network status in AppContext when PPP comes up."""
    if self.context:
        signal_bars = 0
        if self.network_manager and self.network_manager.modem_state.signal:
            signal_bars = self.network_manager.modem_state.signal.bars
        self.context.update_network_status(
            signal_bars=signal_bars,
            connection_type="4g",
            connected=True,
        )
```

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest -q`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add yoyopy/app.py
git commit -m "feat(ui): wire NetworkManager into PowerScreen and GPS events"
```

---

## Task 5: Tests for Setup pages

**Files:**
- Create: `tests/test_network_ui.py`

- [ ] **Step 1: Write tests for Network and GPS pages**

```python
# tests/test_network_ui.py
"""Unit tests for Network and GPS Setup pages."""

from __future__ import annotations

from yoyopy.ui.screens.system.power import PowerPage, PowerScreen
from yoyopy.network.models import GpsCoordinate, ModemPhase, ModemState, SignalInfo


class FakeDisplay:
    """Minimal display double."""

    WIDTH = 240
    HEIGHT = 280
    STATUS_BAR_HEIGHT = 28
    COLOR_BLACK = (0, 0, 0)

    def is_portrait(self) -> bool:
        return True

    def rectangle(self, *args, **kwargs) -> None:
        pass

    def circle(self, *args, **kwargs) -> None:
        pass

    def text(self, *args, **kwargs) -> None:
        pass

    def get_text_size(self, text: str, size: int) -> tuple[int, int]:
        return (len(text) * 6, size)


class FakeNetworkManager:
    """Minimal network manager double."""

    def __init__(self, *, enabled: bool = True, gps_enabled: bool = True, phase: ModemPhase = ModemPhase.ONLINE) -> None:
        self.config = type("Config", (), {"enabled": enabled, "gps_enabled": gps_enabled})()
        self._state = ModemState(
            phase=phase,
            signal=SignalInfo(csq=20),
            carrier="Telekom.de",
            network_type="4G",
            sim_ready=True,
        )

    @property
    def modem_state(self) -> ModemState:
        return self._state


def test_network_page_online():
    """Network page should show Online status with carrier info."""
    nm = FakeNetworkManager(phase=ModemPhase.ONLINE)
    screen = PowerScreen(FakeDisplay(), network_manager=nm)
    rows = screen._build_network_rows()
    assert ("Status", "Online") in rows
    assert ("Carrier", "Telekom.de") in rows
    assert ("Type", "4G") in rows
    assert ("PPP", "Up") in rows


def test_network_page_disabled():
    """Network page should show Disabled when network is off."""
    nm = FakeNetworkManager(enabled=False)
    screen = PowerScreen(FakeDisplay(), network_manager=nm)
    rows = screen._build_network_rows()
    assert rows == [("Status", "Disabled")]


def test_network_page_no_manager():
    """Network page should show Disabled when no network manager."""
    screen = PowerScreen(FakeDisplay())
    rows = screen._build_network_rows()
    assert rows == [("Status", "Disabled")]


def test_gps_page_with_fix():
    """GPS page should show coordinates when fix is available."""
    nm = FakeNetworkManager()
    nm._state.gps = GpsCoordinate(lat=48.8738, lng=2.3522, altitude=349.6, speed=0.0)
    screen = PowerScreen(FakeDisplay(), network_manager=nm)
    rows = screen._build_gps_rows()
    assert ("Fix", "Yes") in rows
    assert any("48.8738" in v for _, v in rows)
    assert any("2.3522" in v for _, v in rows)


def test_gps_page_no_fix():
    """GPS page should show dashes when no GPS fix."""
    nm = FakeNetworkManager()
    screen = PowerScreen(FakeDisplay(), network_manager=nm)
    rows = screen._build_gps_rows()
    assert ("Fix", "No") in rows
    assert ("Lat", "--") in rows


def test_build_pages_includes_network_when_enabled():
    """build_pages should include Network and GPS pages when network is enabled."""
    nm = FakeNetworkManager()
    screen = PowerScreen(FakeDisplay(), network_manager=nm)
    pages = screen.build_pages(snapshot=None, status={})
    titles = [p.title for p in pages]
    assert "Network" in titles
    assert "GPS" in titles
    assert titles.index("Network") == 1  # after Power
    assert titles.index("GPS") == 2  # after Network


def test_build_pages_excludes_network_when_disabled():
    """build_pages should omit Network and GPS pages when network is disabled."""
    screen = PowerScreen(FakeDisplay())
    pages = screen.build_pages(snapshot=None, status={})
    titles = [p.title for p in pages]
    assert "Network" not in titles
    assert "GPS" not in titles
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_network_ui.py -v`
Expected: all 7 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_network_ui.py
git commit -m "test(ui): add tests for Network and GPS Setup pages"
```
