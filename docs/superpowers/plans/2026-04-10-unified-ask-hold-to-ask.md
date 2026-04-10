# Unified Ask Screen + Hold-to-Ask Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three-class Ask submenu with a unified stateful AskScreen (idle/listening/thinking/reply), wire hold-to-ask PTT shortcut from the Hub, and add auto-return after informational commands.

**Architecture:** The PTT adapter fires BACK at the 800ms threshold (instead of on release) and PTT_RELEASE on release. Hub's `on_back` pushes Ask in quick-command mode. The unified AskScreen handles 4 visual states and voice-command logic internally, with PTT capture for the hold-to-ask flow and a 2-second auto-return timer.

**Tech Stack:** Python 3.12+, PIL rendering, pytest, threading

**Specs:**
- `docs/ASK_SCREEN_DESIGN_SPEC.md` — Figma visual spec for the 4 Ask states
- `docs/superpowers/specs/2026-04-10-hold-to-ask-voice-shortcut-design.md` — hold-to-ask interaction design

---

### Task 1: PTT Adapter — Fire BACK at Threshold, PTT_RELEASE on Release

**Files:**
- Modify: `yoyopy/ui/input/adapters/ptt_button.py`
- Test: `tests/test_ptt_adapter.py` (create)

The PTT adapter currently fires BACK on button **release** after a hold. Change it to fire BACK at the 800ms threshold crossing (while still held) and fire PTT_RELEASE on the subsequent release.

- [ ] **Step 1: Write failing tests for new PTT timing**

Create `tests/test_ptt_adapter.py`:

```python
"""Tests for PTT adapter hold-threshold and release behavior."""

from __future__ import annotations

import pytest

from yoyopy.ui.input.hal import InputAction
from yoyopy.ui.input.adapters.ptt_button import PTTInputAdapter


class FakePTTAdapter(PTTInputAdapter):
    """PTT adapter with injectable button state for testing."""

    def __init__(self, **kwargs) -> None:
        super().__init__(simulate=True, **kwargs)
        self._fake_pressed = False

    def _get_button_state(self) -> bool:
        return self._fake_pressed

    def press(self) -> None:
        self._fake_pressed = True

    def release(self) -> None:
        self._fake_pressed = False


def _collect_actions(adapter: FakePTTAdapter) -> list[tuple[str, dict]]:
    """Register callbacks for all actions and return a list of fired (action, data) pairs."""
    fired: list[tuple[str, dict]] = []
    for action in (InputAction.BACK, InputAction.PTT_RELEASE, InputAction.ADVANCE, InputAction.SELECT):
        adapter.on_action(action, lambda data, a=action: fired.append((a.value, data or {})))
    return fired


def test_back_fires_at_hold_threshold_not_on_release():
    """BACK should fire while the button is still held, at the threshold crossing."""
    adapter = FakePTTAdapter(long_press_time=0.05, double_click_time=0.01)
    fired = _collect_actions(adapter)

    import time
    adapter.press()
    adapter._handle_button_press(time.time())

    # Simulate time passing beyond hold threshold
    press_time = adapter.press_start_time
    threshold_time = press_time + 0.06

    # Simulate the poll loop detecting the hold threshold
    adapter.button_pressed = True
    # Manually call the poll-loop logic that detects threshold crossing
    # The button is still pressed — BACK should fire here
    assert adapter._hold_back_fired is False
    # We need to simulate the poll loop behavior
    adapter._check_hold_threshold(threshold_time)
    assert adapter._hold_back_fired is True

    back_events = [e for e in fired if e[0] == "back"]
    assert len(back_events) == 1, "BACK should fire at threshold"

    # Now release — should get PTT_RELEASE, NOT another BACK
    fired.clear()
    adapter.release()
    adapter._handle_button_release(threshold_time + 0.1)

    ptt_release_events = [e for e in fired if e[0] == "ptt_release"]
    back_events = [e for e in fired if e[0] == "back"]
    assert len(ptt_release_events) == 1, "PTT_RELEASE should fire on release after hold"
    assert len(back_events) == 0, "BACK should NOT fire again on release"
    assert ptt_release_events[0][1].get("after_hold") is True


def test_short_press_still_produces_advance():
    """A short tap should still produce ADVANCE, not BACK or PTT_RELEASE."""
    adapter = FakePTTAdapter(long_press_time=0.8, double_click_time=0.01)
    fired = _collect_actions(adapter)

    import time
    now = time.time()
    adapter.press()
    adapter._handle_button_press(now)

    # Release quickly (well under hold threshold)
    adapter.release()
    adapter._handle_button_release(now + 0.05)

    # Wait for double-tap window to expire
    adapter._emit_pending_navigation(now + 0.5)

    advance_events = [e for e in fired if e[0] == "advance"]
    back_events = [e for e in fired if e[0] == "back"]
    ptt_events = [e for e in fired if e[0] == "ptt_release"]
    assert len(advance_events) == 1
    assert len(back_events) == 0
    assert len(ptt_events) == 0


def test_double_tap_still_produces_select():
    """A double-tap should still produce SELECT."""
    adapter = FakePTTAdapter(long_press_time=0.8, double_click_time=0.3)
    fired = _collect_actions(adapter)

    import time
    now = time.time()

    # First tap
    adapter.press()
    adapter._handle_button_press(now)
    adapter.release()
    adapter._handle_button_release(now + 0.05)

    # Second tap within double-click window
    adapter.press()
    adapter._handle_button_press(now + 0.15)
    adapter.release()
    adapter._handle_button_release(now + 0.2)

    select_events = [e for e in fired if e[0] == "select"]
    assert len(select_events) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ptt_adapter.py -v`
Expected: FAIL — `_hold_back_fired` and `_check_hold_threshold` don't exist yet.

- [ ] **Step 3: Implement threshold-based BACK and PTT_RELEASE on release**

In `yoyopy/ui/input/adapters/ptt_button.py`:

Add `self._hold_back_fired = False` to `__init__` after the existing `self.raw_hold_started = False` line.

Add a new method `_check_hold_threshold`:

```python
def _check_hold_threshold(self, current_time: float) -> None:
    """Fire BACK at the hold threshold while the button is still pressed."""
    if (
        not self.enable_navigation
        or self._hold_back_fired
        or self.press_start_time is None
        or self.raw_ptt_passthrough
    ):
        return
    if (current_time - self.press_start_time) >= self.long_press_time:
        self._hold_back_fired = True
        self._fire_action(
            InputAction.BACK,
            {
                "method": "long_hold",
                "duration": current_time - self.press_start_time,
            },
        )
```

In `_poll_button`, add a call to `_check_hold_threshold` in the `elif current_state and previous_state` branch. Replace the existing raw_ptt_passthrough hold detection block (lines 321-337) with:

```python
elif current_state and previous_state and self.press_start_time is not None:
    duration = current_time - self.press_start_time
    if duration >= self.long_press_time:
        if (
            self.raw_ptt_passthrough
            and not self.raw_hold_started
        ):
            self.raw_hold_started = True
            self._fire_action(
                InputAction.PTT_PRESS,
                {
                    "timestamp": current_time,
                    "stage": "hold_started",
                    "duration": duration,
                },
            )
        self._check_hold_threshold(current_time)
```

In `_handle_button_release`, add the `_hold_back_fired` check **before** the existing `press_duration >= self.long_press_time` block (before line 250):

```python
if self._hold_back_fired:
    self._hold_back_fired = False
    self._fire_action(
        InputAction.PTT_RELEASE,
        {
            "timestamp": current_time,
            "duration": press_duration,
            "after_hold": True,
        },
    )
    self.press_start_time = None
    self.pending_single_tap_time = None
    self.double_tap_candidate = False
    self.raw_hold_started = False
    return
```

Also reset `_hold_back_fired = False` in `_handle_button_press` alongside the existing `self.raw_hold_started = False`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ptt_adapter.py -v`
Expected: All 3 tests PASS.

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `uv run pytest -q`
Expected: All existing tests pass. The BACK timing change (threshold vs release) doesn't affect test outcomes since tests use `simulate_action` directly, not the PTT poll loop.

- [ ] **Step 6: Commit**

```bash
git add yoyopy/ui/input/adapters/ptt_button.py tests/test_ptt_adapter.py
git commit -m "feat(input): fire BACK at hold threshold, PTT_RELEASE on release

The PTT adapter now fires BACK when the hold threshold (800ms) is crossed
while the button is still pressed, instead of waiting for release. On
release after a hold, it fires PTT_RELEASE with after_hold=True. This
enables the hold-to-ask push-to-talk flow."
```

---

### Task 2: Update Routes for Unified Ask Screen

**Files:**
- Modify: `yoyopy/ui/screens/router.py`
- Modify: `tests/test_screen_routing.py`

Replace the ask/voice_commands/ai_requests routes with unified ask routes and the hub hold_ask route.

- [ ] **Step 1: Update the routing test**

In `tests/test_screen_routing.py`, replace `test_screen_router_covers_ask_subroutes` (lines 110-127) with:

```python
def test_screen_router_covers_ask_routes() -> None:
    """The unified Ask screen should route call_started and shuffle_started."""
    router = ScreenRouter()

    assert router.resolve("ask", "back") == NavigationRequest.pop()
    assert router.resolve("ask", "call_started") == NavigationRequest.push("outgoing_call")
    assert router.resolve("ask", "shuffle_started") == NavigationRequest.push("now_playing")


def test_screen_router_covers_hub_hold_ask() -> None:
    """Hold on the Hub should route to the Ask screen."""
    router = ScreenRouter()

    assert router.resolve("hub", "hold_ask") == NavigationRequest.push("ask")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_screen_routing.py::test_screen_router_covers_ask_routes tests/test_screen_routing.py::test_screen_router_covers_hub_hold_ask -v`
Expected: FAIL — routes don't exist yet.

- [ ] **Step 3: Update the router**

In `yoyopy/ui/screens/router.py`, in `_default_routes`:

Replace the `"ask"` entry (lines 110-114):
```python
"ask": {
    "back": NavigationRequest.pop(),
    "call_started": NavigationRequest.push("outgoing_call"),
    "shuffle_started": NavigationRequest.push("now_playing"),
},
```

Remove the `"voice_commands"` entry (lines 115-119) and the `"ai_requests"` entry (lines 120-122).

Add `"hold_ask"` to the `"hub"` entry:
```python
"hub": {
    "select:Listen": NavigationRequest.push("listen"),
    "select:Talk": NavigationRequest.push("call"),
    "select:Ask": NavigationRequest.push("ask"),
    "select:Setup": NavigationRequest.push("power"),
    "select:Now Playing": NavigationRequest.push("now_playing"),
    "select:Playlists": NavigationRequest.push("playlists"),
    "select:Calls": NavigationRequest.push("call"),
    "select:Power": NavigationRequest.push("power"),
    "hold_ask": NavigationRequest.push("ask"),
},
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_screen_routing.py -v`
Expected: All routing tests pass. The old `test_screen_router_covers_ask_subroutes` is gone, replaced by the new tests.

- [ ] **Step 5: Commit**

```bash
git add yoyopy/ui/screens/router.py tests/test_screen_routing.py
git commit -m "feat(routing): unify ask routes, add hub hold_ask route

Replace ask/voice_commands/ai_requests routes with a single ask route
that handles call_started and shuffle_started. Add hold_ask route to
hub for the hold-to-ask shortcut."
```

---

### Task 3: Unified AskScreen — Rendering

**Files:**
- Modify: `yoyopy/ui/screens/navigation/ask.py`
- Test: `tests/test_screen_routing.py` (update existing ask test)

Rewrite `AskScreen` as a single stateful screen with 4 visual states. This task focuses on rendering only — voice logic comes in Task 4.

- [ ] **Step 1: Write rendering test for the 4 states**

In `tests/test_screen_routing.py`, replace `test_ask_screen_routes_to_selected_subflow` (lines 248-265) with:

```python
def test_ask_screen_state_transitions() -> None:
    """AskScreen should transition through idle -> listening -> thinking -> reply."""
    ask = AskScreen(display=object(), context=AppContext())

    # Starts in idle
    assert ask._state == "idle"
    assert ask._headline == "Ask"
    assert ask._body == "Ask me anything..."

    # Select transitions to listening (but without voice service, falls back)
    # We test pure state transitions via internal methods
    ask._set_state("listening", "Listening", "Speak now...")
    assert ask._state == "listening"

    ask._set_state("thinking", "Thinking", "Just a moment...")
    assert ask._state == "thinking"

    ask._set_response("Volume", "Volume is 75.")
    assert ask._state == "reply"
    assert ask._headline == "Volume"
    assert ask._body == "Volume is 75."

    # Select from reply goes back to listening
    # (without voice service configured, it will set an error — test the intent)
    ask._set_state("idle", "Ask", "Ask me anything...")
    assert ask._state == "idle"


def test_ask_screen_back_pops() -> None:
    """Back from any Ask state should pop the screen."""
    ask = AskScreen(display=object(), context=AppContext())
    ask.on_back()
    assert ask.consume_navigation_request() == NavigationRequest.route("back")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_screen_routing.py::test_ask_screen_state_transitions tests/test_screen_routing.py::test_ask_screen_back_pops -v`
Expected: FAIL — new AskScreen doesn't have `_set_state` or the correct initial state.

- [ ] **Step 3: Rewrite AskScreen rendering**

Replace the entire `AskScreen` class in `yoyopy/ui/screens/navigation/ask.py`. Keep the imports and the `AskMenuItem` dataclass can be removed. The new class structure:

```python
class AskScreen(Screen):
    """Unified Ask screen with idle/listening/thinking/reply states."""

    _HINT_TEXT = "Ask me anything..."

    # Pre-blended icon circle colors (alpha over BACKGROUND #2A2D35)
    _ICON_CIRCLE_IDLE: tuple[int, int, int] = (74, 69, 45)      # rgba(255,208,0,0.15)
    _ICON_CIRCLE_LISTEN: tuple[int, int, int] = (95, 86, 48)    # rgba(255,208,0,0.25)

    _FAMILY_ALIAS_GROUPS: tuple[tuple[str, ...], ...] = (
        ("mom", "mama", "mum", "mommy", "mother"),
        ("dad", "dada", "daddy", "papa", "father"),
    )

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        *,
        config_manager: Optional["ConfigManager"] = None,
        voip_manager: Optional["VoIPManager"] = None,
        volume_up_action: Optional[Callable[[int], int | None]] = None,
        volume_down_action: Optional[Callable[[int], int | None]] = None,
        mute_action: Optional[Callable[[], bool]] = None,
        unmute_action: Optional[Callable[[], bool]] = None,
        play_music_action: Optional[Callable[[], bool]] = None,
        voice_settings_provider: Optional[Callable[[], VoiceSettings]] = None,
        voice_service_factory: Optional[Callable[[VoiceSettings], VoiceService]] = None,
    ) -> None:
        super().__init__(display, context, "Ask")
        self.config_manager = config_manager
        self.voip_manager = voip_manager
        self.volume_up_action = volume_up_action
        self.volume_down_action = volume_down_action
        self.mute_action = mute_action
        self.unmute_action = unmute_action
        self.play_music_action = play_music_action
        self.voice_settings_provider = voice_settings_provider
        self.voice_service_factory = voice_service_factory
        self._cached_voice_service: VoiceService | None = None
        self._state = "idle"
        self._headline = "Ask"
        self._body = self._HINT_TEXT
        self._quick_command = False
        self._ptt_active = False
        self._capture_in_flight = False
        self._listen_generation = 0
        self._active_capture_cancel: threading.Event | None = None
        self._auto_return_timer: threading.Timer | None = None
        self._output_player = AlsaOutputPlayer()

    def set_quick_command(self, enabled: bool) -> None:
        """Mark the next entry as a quick-command (hold-to-ask) session."""
        self._quick_command = enabled

    def enter(self) -> None:
        super().enter()
        self._cancel_listening_cycle()
        self._cancel_auto_return()
        if self._quick_command:
            self._start_ptt_capture()
        else:
            self._state = "idle"
            self._headline = "Ask"
            self._body = self._HINT_TEXT

    def exit(self) -> None:
        self._cancel_listening_cycle()
        self._cancel_auto_return()
        self._quick_command = False
        super().exit()

    def _set_state(self, state: str, headline: str, body: str) -> None:
        """Update the screen state and text for rendering."""
        self._state = state
        self._headline = headline
        self._body = body

    def _set_response(self, headline: str, body: str) -> None:
        """Set the reply state with a headline and body."""
        self._state = "reply"
        self._headline = headline
        self._body = body

    def render(self) -> None:
        if self._state == "reply":
            self._render_reply()
        else:
            self._render_icon_state()

    def _render_icon_state(self) -> None:
        """Render idle, listening, or thinking state with centered icon."""
        content_top = render_header(
            self.display, self.context, mode="ask", title="Ask", show_time=True,
            show_mode_chip=False,
        )

        # Icon circle
        circle_size = 112
        circle_left = (self.display.WIDTH - circle_size) // 2
        circle_top = content_top + 16
        circle_fill = (
            self._ICON_CIRCLE_LISTEN if self._state == "listening"
            else self._ICON_CIRCLE_IDLE
        )
        self.display.circle_filled(
            circle_left + circle_size // 2,
            circle_top + circle_size // 2,
            circle_size // 2,
            fill=circle_fill,
        )

        # Icon (56x56 centered in the 112x112 circle)
        icon_size = 56
        draw_icon(
            self.display, "ask",
            circle_left + (circle_size - icon_size) // 2,
            circle_top + (circle_size - icon_size) // 2,
            icon_size, ASK.accent,
        )

        # Heading
        heading = text_fit(self.display, self._headline, self.display.WIDTH - 40, 20)
        heading_width, _ = self.display.get_text_size(heading, 20)
        self.display.text(
            heading,
            (self.display.WIDTH - heading_width) // 2,
            content_top + 144,
            color=INK, font_size=20,
        )

        # Subtitle
        subtitle_color = MUTED_DIM if self._state == "thinking" else ASK.accent
        subtitle = text_fit(self.display, self._body, self.display.WIDTH - 40, 14)
        subtitle_width, _ = self.display.get_text_size(subtitle, 14)
        self.display.text(
            subtitle,
            (self.display.WIDTH - subtitle_width) // 2,
            content_top + 180,
            color=subtitle_color, font_size=14,
        )

        self._render_hint_bar()
        self.display.update()

    def _render_reply(self) -> None:
        """Render the reply state with left-aligned wrapped text."""
        content_top = render_header(
            self.display, self.context, mode="ask", title="Ask", show_time=True,
            show_mode_chip=False,
        )

        text_x = 24
        text_y = content_top + 16
        text_width = 183
        line_height = 23

        for line in wrap_text(self.display, self._body, text_width, 14, max_lines=8):
            self.display.text(line, text_x, text_y, color=MUTED, font_size=14)
            text_y += line_height

        self._render_hint_bar()
        self.display.update()

    def _render_hint_bar(self) -> None:
        """Render the state-appropriate hint bar."""
        if self._state == "idle":
            hint = "2× Tap = Ask · Hold = Back" if self.is_one_button_mode() else "A ask | B back"
        elif self._state == "listening":
            hint = "Speaking... · Hold = Cancel" if self.is_one_button_mode() else "A (recording) | B cancel"
        elif self._state == "thinking":
            hint = "Processing..."
        else:
            hint = "2× Tap = Ask Again · Hold = Back" if self.is_one_button_mode() else "A ask again | B back"
        render_footer(self.display, hint, mode="ask")
```

Note: if `self.display.circle_filled` doesn't exist, use PIL's `ImageDraw.ellipse` via the existing display abstraction. Check the Display class and use whatever filled-circle primitive is available, or fall back to `rounded_panel` with equal width/height and `radius=circle_size//2`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_screen_routing.py::test_ask_screen_state_transitions tests/test_screen_routing.py::test_ask_screen_back_pops -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add yoyopy/ui/screens/navigation/ask.py tests/test_screen_routing.py
git commit -m "feat(ask): unified AskScreen with 4-state rendering

Replace the AskScreen submenu with a stateful screen that renders
idle, listening, thinking, and reply states matching the Figma spec.
Rendering only — voice logic is wired in the next task."
```

---

### Task 4: Unified AskScreen — Voice Command Logic

**Files:**
- Modify: `yoyopy/ui/screens/navigation/ask.py`
- Modify: `tests/test_screen_routing.py`

Migrate all voice-command logic from the old `VoiceCommandsScreen` into the unified `AskScreen`. This includes: capture, transcription, command matching, contact lookup, volume/mute/play handlers, TTS, and the listening cycle.

- [ ] **Step 1: Update voice command tests to use AskScreen**

In `tests/test_screen_routing.py`, update the existing voice command tests. Replace every `VoiceCommandsScreen(` with `AskScreen(` in the test functions from `test_voice_commands_screen_applies_local_device_actions` through `test_voice_commands_screen_ignores_stale_results_after_back`. Also update the import at the top to remove `VoiceCommandsScreen` from the import.

For example, change:
```python
screen = VoiceCommandsScreen(
    display=object(),
    context=context,
    ...
)
```
to:
```python
screen = AskScreen(
    display=object(),
    context=context,
    ...
)
```

Rename the test functions from `test_voice_commands_screen_*` to `test_ask_screen_*` for consistency.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_screen_routing.py -k "test_ask_screen" -v`
Expected: FAIL — the new AskScreen doesn't have voice logic yet.

- [ ] **Step 3: Add voice command logic to AskScreen**

Add these methods to the `AskScreen` class in `ask.py`. These are moved directly from the old `VoiceCommandsScreen` with minimal changes. Add them after the rendering methods:

```python
    # --- Input handlers ---

    def on_select(self, data=None) -> None:
        """Start listening or ask again from reply."""
        if self._capture_in_flight:
            return
        if self._state == "reply" or self._state == "idle":
            self._start_listening_cycle(async_capture=self.voice_service_factory is None)

    def on_advance(self, data=None) -> None:
        """Advance is unused on the Ask screen."""

    def on_back(self, data=None) -> None:
        """Return to the previous screen."""
        self._cancel_listening_cycle()
        self._cancel_auto_return()
        self.request_route("back")

    def on_voice_command(self, data=None) -> None:
        """Parse and execute a deterministic local voice command."""
        transcript = self._extract_transcript(data)
        if not transcript:
            self._set_response("No Speech", "I did not catch a command.")
            return

        if self.context is not None:
            self.context.record_voice_transcript(transcript, mode="voice_commands")

        command = self._voice_service().match_command(transcript)
        if not command.is_command:
            self._speak_response(
                "Not Recognized",
                f"I heard '{transcript}' but that is not a voice command. Try: call mom, play music, or volume up.",
            )
            return

        if command.intent is VoiceCommandIntent.CALL_CONTACT:
            self._handle_call_command(command.contact_name)
            return
        if command.intent is VoiceCommandIntent.VOLUME_UP:
            self._handle_volume_change(+5)
            return
        if command.intent is VoiceCommandIntent.VOLUME_DOWN:
            self._handle_volume_change(-5)
            return
        if command.intent is VoiceCommandIntent.PLAY_MUSIC:
            self._handle_play_music_command()
            return
        if command.intent is VoiceCommandIntent.MUTE_MIC:
            self._apply_mic_state(muted=True)
            self._speak_response("Mic Muted", "Voice commands mic is muted.")
            return
        if command.intent is VoiceCommandIntent.UNMUTE_MIC:
            self._apply_mic_state(muted=False)
            self._speak_response("Mic Live", "Voice commands mic is live.")
            return
        if command.intent is VoiceCommandIntent.READ_SCREEN:
            self._speak_response("Screen Read", self._screen_summary())
            return

        self._set_response("Not Ready", "That command is recognized but not wired yet.")
```

Then add the full set of private methods. These are copied directly from the old `VoiceCommandsScreen` — all methods from `_extract_transcript` through `_sync_context_output_volume`, plus `_start_listening_cycle`, `_run_listening_cycle`, `_dispatch_listen_result`, `_refresh_after_state_change`, `_play_attention_tone`, `_write_beep_wav`, `_cancel_listening_cycle`.

The only change: in `_start_listening_cycle`, transition to `"listening"` state using `_set_state`:
```python
self._set_state("listening", "Listening", "Speak now...")
```

And in `_dispatch_listen_result`, before calling `on_voice_command`, transition to `"thinking"`:
```python
def apply_result() -> None:
    if generation != self._listen_generation:
        return
    self._active_capture_cancel = None
    self._capture_in_flight = False
    if capture_failed:
        self._set_response("Mic Unavailable", "The Pi microphone input is busy or unavailable.")
    elif transcript:
        self._set_state("thinking", "Thinking", "Just a moment...")
        self._refresh_after_state_change()
        self.on_voice_command({"transcript": transcript})
    else:
        self._set_response("No Speech", "I did not catch a command.")
    self._refresh_after_state_change()
    if self._quick_command:
        self._schedule_auto_return()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_screen_routing.py -k "test_ask_screen" -v`
Expected: All ask screen tests PASS.

- [ ] **Step 5: Commit**

```bash
git add yoyopy/ui/screens/navigation/ask.py tests/test_screen_routing.py
git commit -m "feat(ask): migrate voice command logic into unified AskScreen

Move capture, transcription, command matching, contact lookup, volume,
mute, play, and TTS logic from VoiceCommandsScreen into the unified
AskScreen class."
```

---

### Task 5: Quick-Command Mode + PTT Capture

**Files:**
- Modify: `yoyopy/ui/screens/navigation/ask.py`
- Modify: `tests/test_screen_routing.py`

Add the hold-to-ask PTT capture flow: `set_quick_command`, `_start_ptt_capture`, `on_ptt_release`, and the 2-second auto-return timer.

- [ ] **Step 1: Write tests for quick-command mode**

Add to `tests/test_screen_routing.py`:

```python
def test_ask_screen_quick_command_skips_idle() -> None:
    """Quick-command mode should skip idle and go straight to listening."""
    context = AppContext()
    service = _FakeVoiceService("volume up")
    ask = AskScreen(
        display=object(),
        context=context,
        voice_settings_provider=lambda: VoiceSettings(),
        voice_service_factory=lambda _s: service,
    )

    ask.set_quick_command(True)
    ask.enter()

    # Should be in listening state, not idle
    assert ask._state == "listening"
    assert ask._ptt_active is True
    assert ask._quick_command is True


def test_ask_screen_ptt_release_stops_capture() -> None:
    """PTT_RELEASE should stop the capture and process the result."""
    context = AppContext()
    service = _FakeVoiceService("volume up")
    ask = AskScreen(
        display=object(),
        context=context,
        volume_up_action=lambda step: 55,
        voice_settings_provider=lambda: VoiceSettings(),
        voice_service_factory=lambda _s: service,
    )

    ask.set_quick_command(True)
    ask.enter()

    # Simulate PTT release
    ask.on_ptt_release({"after_hold": True})

    assert ask._ptt_active is False


def test_ask_screen_auto_return_only_in_quick_command() -> None:
    """Auto-return should only schedule in quick-command mode."""
    ask = AskScreen(display=object(), context=AppContext())

    ask._quick_command = False
    ask._schedule_auto_return()
    assert ask._auto_return_timer is None

    ask._quick_command = True
    ask._schedule_auto_return()
    assert ask._auto_return_timer is not None
    ask._cancel_auto_return()


def test_ask_screen_exit_clears_quick_command() -> None:
    """Exiting the screen should reset the quick-command flag."""
    ask = AskScreen(display=object(), context=AppContext())
    ask._quick_command = True
    ask.exit()
    assert ask._quick_command is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_screen_routing.py -k "test_ask_screen_quick" -v`
Expected: FAIL — PTT methods not wired yet.

- [ ] **Step 3: Add PTT capture and auto-return to AskScreen**

Add these methods to `AskScreen` in `ask.py`:

```python
    def _start_ptt_capture(self) -> None:
        """Begin open-ended recording that stops on PTT_RELEASE."""
        if self.context is not None and not self.context.voice.commands_enabled:
            self._set_response("Voice Off", "Turn voice commands on in Setup first.")
            self._refresh_after_state_change()
            return
        if self.context is not None and self.context.voice.mic_muted:
            self._set_response("Mic Muted", "Unmute the microphone first.")
            self._refresh_after_state_change()
            return

        voice_service = self._voice_service()
        if not voice_service.capture_available() or not voice_service.stt_available():
            self._set_response("Mic Unavailable", "Voice capture is not ready on this device.")
            self._refresh_after_state_change()
            return

        self._capture_in_flight = True
        self._ptt_active = True
        self._set_state("listening", "Listening", "Speak now...")
        self._refresh_after_state_change()
        self._listen_generation += 1
        generation = self._listen_generation
        cancel_event = threading.Event()
        self._active_capture_cancel = cancel_event

        self._play_attention_tone()

        threading.Thread(
            target=self._run_ptt_listening_cycle,
            args=(voice_service, generation, cancel_event),
            daemon=True,
            name="AskPTTCapture",
        ).start()

    def _run_ptt_listening_cycle(
        self,
        voice_service: VoiceService,
        generation: int,
        cancel_event: threading.Event,
    ) -> None:
        """Record until cancel_event is set (by PTT_RELEASE), then transcribe."""
        request = VoiceCaptureRequest(
            mode="voice_commands",
            timeout_seconds=30.0,
            cancel_event=cancel_event,
        )
        capture_result = voice_service.capture_audio(request)

        if generation != self._listen_generation:
            if capture_result.audio_path is not None:
                capture_result.audio_path.unlink(missing_ok=True)
            return

        # If PTT was released (not cancelled by back/exit), process the audio
        if not self._ptt_active and capture_result.audio_path is not None:
            try:
                transcript = voice_service.transcribe(capture_result.audio_path)
            except Exception as exc:
                logger.warning("PTT transcription failed: {}", exc)
                self._dispatch_listen_result("", capture_failed=True, generation=generation)
                return
            finally:
                capture_result.audio_path.unlink(missing_ok=True)

            self._dispatch_listen_result(
                transcript.text.strip(), capture_failed=False, generation=generation,
            )
        elif capture_result.audio_path is not None:
            # Cancelled by back/exit — discard
            capture_result.audio_path.unlink(missing_ok=True)

    def on_ptt_release(self, data=None) -> None:
        """Stop PTT recording when the button is released after a hold."""
        if self._ptt_active and self._active_capture_cancel is not None:
            self._ptt_active = False
            self._active_capture_cancel.set()

    def _schedule_auto_return(self) -> None:
        """Pop back after 2 seconds in quick-command mode."""
        if not self._quick_command:
            return
        self._cancel_auto_return()
        self._auto_return_timer = threading.Timer(2.0, self._auto_pop)
        self._auto_return_timer.daemon = True
        self._auto_return_timer.start()

    def _auto_pop(self) -> None:
        """Return to the previous screen via the action scheduler."""
        self._auto_return_timer = None
        scheduler = (
            getattr(self.screen_manager, "action_scheduler", None)
            if self.screen_manager is not None
            else None
        )
        if scheduler is not None:
            scheduler(lambda: self.request_route("back"))
        else:
            self.request_route("back")

    def _cancel_auto_return(self) -> None:
        """Cancel any pending auto-return timer."""
        if self._auto_return_timer is not None:
            self._auto_return_timer.cancel()
            self._auto_return_timer = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_screen_routing.py -k "test_ask_screen" -v`
Expected: All ask screen tests PASS.

- [ ] **Step 5: Commit**

```bash
git add yoyopy/ui/screens/navigation/ask.py tests/test_screen_routing.py
git commit -m "feat(ask): add quick-command PTT capture and auto-return

Quick-command mode (set via set_quick_command) skips idle and starts
PTT recording immediately. on_ptt_release stops capture. A 2-second
auto-return timer pops back to the previous screen after informational
commands."
```

---

### Task 6: Hub Hold-to-Ask Wiring

**Files:**
- Modify: `yoyopy/ui/screens/navigation/hub.py`
- Modify: `tests/test_screen_routing.py`

Wire the Hub's `on_back` to push Ask in quick-command mode and update the footer hint.

- [ ] **Step 1: Write test for Hub hold-to-ask**

Add to `tests/test_screen_routing.py`:

```python
def test_hub_back_triggers_hold_ask_route(display: Display) -> None:
    """Holding on the Hub should push Ask via the hold_ask route."""
    context = AppContext()
    input_manager = InputManager()
    screen_manager = ScreenManager(display, input_manager)

    hub = HubScreen(display, context)
    ask = AskScreen(display=display, context=context)

    screen_manager.register_screen("hub", hub)
    screen_manager.register_screen("ask", ask)
    screen_manager.replace_screen("hub")

    # Simulate hold (BACK action)
    input_manager.simulate_action(InputAction.BACK)

    assert screen_manager.current_screen is ask
    assert ask._quick_command is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_screen_routing.py::test_hub_back_triggers_hold_ask_route -v`
Expected: FAIL — Hub on_back is still a no-op.

- [ ] **Step 3: Update Hub on_back and footer**

In `yoyopy/ui/screens/navigation/hub.py`, replace `on_back` (lines 264-266):

```python
def on_back(self, data=None) -> None:
    """Open Ask in quick-command mode (hold-to-ask shortcut)."""
    if self.screen_manager is not None:
        ask_screen = self.screen_manager.screens.get("ask")
        if ask_screen is not None and hasattr(ask_screen, "set_quick_command"):
            ask_screen.set_quick_command(True)
    self.request_route("hold_ask")
```

Update the footer text (line 245):
```python
footer_text = "Tap = Next · 2× = Open · Hold = Ask"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_screen_routing.py::test_hub_back_triggers_hold_ask_route -v`
Expected: PASS.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -q`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add yoyopy/ui/screens/navigation/hub.py tests/test_screen_routing.py
git commit -m "feat(hub): wire hold-to-ask shortcut from Hub

Hub on_back now sets quick_command on the Ask screen and pushes it via
the hold_ask route. Footer text updated to show the Hold = Ask hint."
```

---

### Task 7: Remove Old Classes and Update Exports

**Files:**
- Modify: `yoyopy/ui/screens/navigation/ask.py`
- Modify: `yoyopy/ui/screens/navigation/__init__.py`
- Modify: `yoyopy/ui/screens/__init__.py`
- Modify: `yoyopy/app.py`

Remove `VoiceCommandsScreen`, `AIRequestsScreen`, and the old `AskMenuItem` dataclass. Update all module exports and screen registration in `app.py`.

- [ ] **Step 1: Remove old classes from ask.py**

Delete the `AskMenuItem` dataclass, the old `VoiceCommandsScreen` class, and the old `AIRequestsScreen` class from `yoyopy/ui/screens/navigation/ask.py`. Only the new unified `AskScreen` should remain.

- [ ] **Step 2: Update navigation __init__.py**

In `yoyopy/ui/screens/navigation/__init__.py`, change line 7:
```python
from yoyopy.ui.screens.navigation.ask import AskScreen
```

Update `__all__`:
```python
__all__ = ['HubScreen', 'HomeScreen', 'ListenScreen', 'MenuScreen', 'AskScreen']
```

- [ ] **Step 3: Update screens __init__.py**

In `yoyopy/ui/screens/__init__.py`, change line 22:
```python
from yoyopy.ui.screens.navigation import AskScreen, HubScreen, HomeScreen, ListenScreen, MenuScreen
```

Remove `VoiceCommandsScreen` and `AIRequestsScreen` from `__all__` (lines 52-54).

- [ ] **Step 4: Update app.py screen registration**

In `yoyopy/app.py`, remove the `VoiceCommandsScreen` and `AIRequestsScreen` instantiation and registration. The unified `AskScreen` should receive all the constructor arguments that `VoiceCommandsScreen` currently receives. Remove lines that register `voice_commands` and `ai_requests` screens.

The `AskScreen` registration should look like:
```python
self.ask_screen = AskScreen(
    self.display,
    self.context,
    config_manager=self.config_manager,
    voip_manager=self.voip_manager,
    volume_up_action=...,       # same as current VoiceCommandsScreen
    volume_down_action=...,     # same
    mute_action=...,            # same
    unmute_action=...,          # same
    play_music_action=...,      # same
    voice_settings_provider=..., # same
)
self.screen_manager.register_screen("ask", self.ask_screen)
# Remove: self.screen_manager.register_screen("voice_commands", ...)
# Remove: self.screen_manager.register_screen("ai_requests", ...)
```

- [ ] **Step 5: Update test imports**

In `tests/test_screen_routing.py`, remove `VoiceCommandsScreen` from the import statement on line 26. It should only import `AskScreen`.

- [ ] **Step 6: Verify compilation**

Run: `python -m compileall yoyopy tests`
Expected: No syntax errors.

- [ ] **Step 7: Run full test suite**

Run: `uv run pytest -q`
Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
git add yoyopy/ui/screens/navigation/ask.py yoyopy/ui/screens/navigation/__init__.py yoyopy/ui/screens/__init__.py yoyopy/app.py tests/test_screen_routing.py
git commit -m "refactor(ask): remove VoiceCommandsScreen and AIRequestsScreen

Clean up the old three-class architecture. Only the unified AskScreen
remains. Module exports, app registration, and test imports updated."
```

---

### Task 8: Final Integration Verification

**Files:**
- Test: all existing test files

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -q`
Expected: All tests pass.

- [ ] **Step 2: Run compilation check**

Run: `python -m compileall yoyopy tests demos scripts`
Expected: No errors.

- [ ] **Step 3: Verify the app starts in simulation mode**

Run: `python yoyopod.py --simulate`
Expected: App launches, Hub shows "Hold = Ask" in footer, Ask screen is reachable via double-tap on Hub when Ask card is selected.

- [ ] **Step 4: Commit any remaining fixes**

If any issues were found, fix and commit.

```bash
git commit -m "fix: address integration issues from ask screen unification"
```
