# Ask Screen Design Specification

**Status:** Design target for the unified `Ask` experience, not the standalone current implementation contract
**Source:** Figma YoYoPod-Design, node `43:4677` (Ask section)
**Extracted:** 2026-04-10
**Target:** 240x280 Whisplay portrait display
**Rendering path:** LVGL-driven Ask scene in `yoyopod/ui/screens/navigation/ask/__init__.py`

> Current note: use this file for intended interaction and visual design. For what actually exists on `main`, trust `docs/architecture/SYSTEM_ARCHITECTURE.md`, the current `AskScreen` implementation, and the current router/screen registration code.

---

## Design Overview

The Figma design shows a **unified Ask screen with 4 visual states** — not a submenu routing to sub-screens. This replaces the current three-class architecture (`AskScreen` submenu + `VoiceCommandsScreen` + `AIRequestsScreen`) with a single `AskScreen` class that manages its own state machine: `idle` -> `listening` -> `thinking` -> `reply`.

### Figma Screenshots (reference)

| State | Figma Node | Key Visual |
|---|---|---|
| Idle | `43:5658` | Sparkle icon in muted circle, "Ask", "Ask me anything..." |
| Listening | `43:5694` | Same icon with yellow glow, "Listening", "Speak now..." |
| Thinking | `43:5730` | Rotated sparkle icon, "Thinking", "Just a moment..." |
| Reply | `43:5763` | No icon — full-width text response area |

---

## Architecture Change

### Current (to be replaced)

```
AskScreen (submenu) -> routes to:
  ├── VoiceCommandsScreen (voice_commands)
  └── AIRequestsScreen (ai_requests)
```

### Target (unified)

```
AskScreen (single screen, 4 internal states)
  ├── idle       — entry state, waiting for user action
  ├── listening  — capturing voice input
  ├── thinking   — processing/transcribing
  └── reply      — showing response text
```

### Routing changes

The `ask` route in `router.py` currently has:

```python
"ask": {
    "back": NavigationRequest.pop(),
    "select:Voice Commands": NavigationRequest.push("voice_commands"),
    "select:AI Requests": NavigationRequest.push("ai_requests"),
},
```

Replace with:

```python
"ask": {
    "back": NavigationRequest.pop(),
    "call_started": NavigationRequest.push("outgoing_call"),
    "shuffle_started": NavigationRequest.push("now_playing"),
},
```

The `voice_commands` and `ai_requests` routes can be removed. The `AskScreen` no longer routes to sub-screens; it handles all states internally and only routes out for side effects (call started, shuffle started, back).

### Screen registration

In `app.py` (or wherever screens are registered with the manager), replace the three screen registrations:

```python
# Remove these:
manager.register("ask", AskScreen(...))
manager.register("voice_commands", VoiceCommandsScreen(...))
manager.register("ai_requests", AIRequestsScreen(...))

# Replace with:
manager.register("ask", AskScreen(...))
```

The new `AskScreen` takes the same constructor dependencies that `VoiceCommandsScreen` currently takes (config_manager, voip_manager, volume/mute/play actions, voice service).

---

## Common Layout (all 4 states)

All states share the same 240x280 frame structure:

```
┌─────────────────────────────┐  ← y=0
│  StatusBar (32.5px)         │     render_header handles this
├─────────────────────────────┤  ← y=32.5 (content_top)
│                             │
│  Content Area (216px)       │     state-specific rendering
│                             │
├─────────────────────────────┤  ← y=248.5
│  HintBar (32px)             │     render_footer handles this
└─────────────────────────────┘  ← y=280
```

- **Background:** `#2A2D35` — matches existing `BACKGROUND = (42, 45, 53)`
- **StatusBar:** rendered by `render_header` with `mode="ask"`, `show_time=True`
- **HintBar:** rendered by `render_footer`, bg `#1F2127` — matches `FOOTER_BAR = (31, 33, 39)`

---

## State: Idle

**Visual:** Large centered sparkle icon in a muted yellow circle, "Ask" heading, "Ask me anything..." call-to-action.

### Layout specs

| Element | Position | Size | Style |
|---|---|---|---|
| AskIcon circle | centered, y=16 from content_top | 112x112 | bg `rgba(255, 208, 0, 0.15)`, fully rounded |
| Sparkle icon | centered inside circle | 56x56 | ASK accent color `#FFD000` |
| Heading "Ask" | centered, y=144 from content_top | auto | Fredoka SemiBold 20px, white `#FFFFFF` |
| Subtitle | centered, y=180 from content_top | auto | Inter SemiBold 14px, `#FFD000` (ASK accent) |

### Colors

- Icon circle background: `rgba(255, 208, 0, 0.15)` — use `(255, 208, 0)` at 15% alpha blended with background, which yields approximately `(74, 69, 45)` when blended over `#2A2D35`
- Use the live theme/display primitives to draw a filled circle with the blended color
- Icon: use existing `draw_icon("ask", ...)` with `ASK.accent` color `(255, 208, 0)`
- Heading: white `(255, 255, 255)` — existing `INK`
- Subtitle text: `(255, 208, 0)` — existing `ASK.accent`

### HintBar

```
"2× Tap = Ask  ·  Hold = Back"
```

- Font: Inter Regular 12px
- Color: `#7A7D84` — existing `MUTED_DIM = (122, 125, 132)`
- Opacity: 70% on left/right text, 50% on the `·` separator
- Use `render_footer` — the hint text is: `"2× Tap = Ask · Hold = Back"` (one-button mode) or `"A ask | B back"` (four-button mode)

### Behavior

- This is the entry state when the Ask screen is pushed.
- `on_select` / double-tap → transition to `listening`
- `on_back` / hold → pop screen (route "back")

---

## State: Listening

**Visual:** Same layout as Idle but the icon circle is brighter and glows, heading changes to "Listening", subtitle to "Speak now...".

### Differences from Idle

| Element | Change from Idle |
|---|---|
| AskIcon circle bg | `rgba(255, 208, 0, 0.25)` — brighter (25% alpha vs 15%) |
| AskIcon glow | `box-shadow: 0 0 32px rgba(255, 208, 0, 0.4)` — yellow glow around circle |
| Heading | "Listening" (white, same font) |
| Subtitle | "Speak now..." (same `#FFD000` accent, same Inter SemiBold 14px) |

### Glow implementation in the live runtime

The glow effect can be approximated by:
1. Drawing a slightly larger, semi-transparent yellow circle behind the main icon circle
2. Or simply using a brighter circle fill without glow (acceptable simplification for 240x280)

Blended circle color at 25% alpha over `#2A2D35`: approximately `(95, 86, 48)`

### HintBar

```
"Speaking...  ·  Hold = Cancel"
```

- One-button mode: `"Speaking... · Hold = Cancel"`
- Four-button mode: `"A (recording) | B cancel"`

### Behavior

- Voice capture is active — the screen entered this state because `on_select` was pressed
- Auto-listen on entry is also supported (existing behavior to preserve)
- When capture completes → transition to `thinking`
- When capture fails → transition to `reply` with error message
- `on_back` / hold → cancel capture, transition back to `idle` or pop

---

## State: Thinking

**Visual:** Same centered-icon layout but the sparkle icon is rotated ~44 degrees, subtitle is muted (not yellow), hint bar shows only "Processing..." centered.

### Differences from Idle/Listening

| Element | Change |
|---|---|
| AskIcon circle bg | `rgba(255, 208, 0, 0.15)` — same as idle (no glow) |
| Icon rotation | Sparkle rotated 43.9 degrees |
| Heading | "Thinking" (white) |
| Subtitle | "Just a moment..." — **Inter Regular 14px, `#7A7D84` (MUTED_DIM)** — NOT yellow |
| HintBar | Single centered text "Processing..." — no left/right split |

### Icon rotation in the live runtime

The icon rotation can be implemented by:
- If using `draw_icon`, pass a rotation parameter or pre-rotate the icon image
- Or draw the standard icon and note that exact rotation is a nice-to-have if the retained scene does not expose it directly
- Acceptable simplification: use the standard icon without rotation while preserving the design intent

### HintBar

```
"Processing..."
```

- Single centered text, no `·` separator, no left/right split
- Use `render_footer` with just the centered text

### Behavior

- Brief transitional state while transcription/processing runs
- Automatically transitions to `reply` when result is ready
- No user actions available (no select, no advance)
- `on_back` is still available to cancel

---

## State: Reply

**Visual:** Completely different layout — no icon circle, no heading. The entire content area is a left-aligned text block showing the response.

### Layout specs

| Element | Position | Size | Style |
|---|---|---|---|
| Text container | x=24, y=16 from content_top | 192px wide, ~183px tall | overflow clipped |
| Response text | inside container | wraps at 183px | Inter Regular 14px, `#B4B7BE`, line-height ~22.75px |

### Colors

- Response text: `#B4B7BE` — existing `MUTED = (180, 183, 190)`
- No accent color in this state

### HintBar

```
"2× Tap = Ask Again  ·  Hold = Back"
```

- One-button mode: `"2× Tap = Ask Again · Hold = Back"`
- Four-button mode: `"A ask again | B back"`

### Text rendering

- Left-aligned (NOT centered like the other states)
- Use `wrap_text` with width `183` (192 container - some padding)
- Line height: approximately 23px per line (22.75px in Figma)
- Max visible lines: ~8 lines in the 183px tall container (183 / 23 ≈ 8)
- Font: Inter Regular 14px
- Color: MUTED `(180, 183, 190)`

### Behavior

- Shows the voice command result or AI response text
- `on_select` / double-tap → transition back to `listening` (ask again)
- `on_back` / hold → pop screen

---

## Consolidated Color Reference

| Token | Hex | RGB | Usage |
|---|---|---|---|
| BACKGROUND | `#2A2D35` | `(42, 45, 53)` | Screen background |
| FOOTER_BAR | `#1F2127` | `(31, 33, 39)` | HintBar background |
| INK | `#FFFFFF` | `(255, 255, 255)` | Headings |
| MUTED | `#B4B7BE` | `(180, 183, 190)` | Reply text |
| MUTED_DIM | `#7A7D84` | `(122, 125, 132)` | HintBar text, Thinking subtitle |
| ASK.accent | `#FFD000` | `(255, 208, 0)` | Icon, Idle/Listening subtitle |
| Icon circle (idle/thinking) | `rgba(255,208,0,0.15)` | ~`(74, 69, 45)` | 15% alpha over bg |
| Icon circle (listening) | `rgba(255,208,0,0.25)` | ~`(95, 86, 48)` | 25% alpha over bg |

---

## Typography Reference

| Element | Font | Weight | Size | Line Height |
|---|---|---|---|---|
| Heading | Fredoka | SemiBold (600) | 20px | 28px |
| Subtitle (idle/listening) | Inter | SemiBold (600) | 14px | 20px |
| Subtitle (thinking) | Inter | Regular (400) | 14px | 20px |
| Reply text | Inter | Regular (400) | 14px | 22.75px |
| HintBar | Inter | Regular (400) | 12px | 16px |
| StatusBar time | Inter | Medium (500) | 11px | 16.5px |

---

## Implementation Approach

### Step 1: Refactor `AskScreen` class

Replace the current `AskScreen` (submenu), `VoiceCommandsScreen`, and `AIRequestsScreen` with a single unified `AskScreen` class.

**Key structure:**

```python
class AskScreen(Screen):
    # States: "idle", "listening", "thinking", "reply"
    _state: str
    _headline: str
    _body: str

    def render(self):
        if self._state == "reply":
            self._render_reply()
        else:
            self._render_icon_state()

    def _render_icon_state(self):
        # Shared layout for idle/listening/thinking
        # 1. render_header (status bar)
        # 2. Draw icon circle (size/color varies by state)
        # 3. Draw centered heading
        # 4. Draw centered subtitle
        # 5. render_footer (hint bar with state-specific text)

    def _render_reply(self):
        # Reply layout
        # 1. render_header (status bar)
        # 2. Draw left-aligned wrapped response text
        # 3. render_footer (hint bar)
```

### Step 2: Move voice-command logic into the unified class

The voice capture, transcription, and command-matching logic from `VoiceCommandsScreen` moves into the new `AskScreen`. The state transitions become:

```
idle --[on_select]--> listening
listening --[capture_done]--> thinking
thinking --[transcribe_done]--> reply
reply --[on_select]--> listening  (ask again)
any --[on_back]--> pop
```

### Step 3: Icon circle rendering

Add a helper (or extend existing `draw_icon`) to render the large centered icon circle:

```python
def _draw_ask_icon_circle(self, content_top: int) -> None:
    cx = self.display.WIDTH // 2
    cy = content_top + 16 + 56  # center of 112px circle
    radius = 56

    # Choose circle fill based on state
    if self._state == "listening":
        fill = (95, 86, 48)   # 25% alpha yellow over bg
        # Optional: draw a slightly larger circle for glow
    else:
        fill = (74, 69, 45)   # 15% alpha yellow over bg

    # Draw filled circle
    # Draw icon centered at (cx, cy), size 56x56
    draw_icon(self.display, "ask", cx - 28, content_top + 16 + 28, 56, ASK.accent)
```

### Step 4: Update routes and screen registration

- Remove `voice_commands` and `ai_requests` routes from `router.py`
- Remove `VoiceCommandsScreen` and `AIRequestsScreen` class registrations
- Keep the `ask` route with `back`, `call_started`, `shuffle_started`

### Step 5: Preserve existing voice command behavior

All the existing voice-command handling from `VoiceCommandsScreen` must be preserved:
- Contact lookup and call initiation
- Volume up/down commands
- Play music command
- Mute/unmute mic commands
- Screen read command
- Auto-listen on entry
- Attention beep tone
- TTS spoken responses

The business logic doesn't change — only the visual presentation and screen architecture.

---

## Existing Theme Helpers To Reuse

From `yoyopod/ui/screens/theme.py`:
- `render_header()` — status bar with time, battery, mode chip
- `render_footer()` — hint bar with help text
- `draw_icon()` — icon rendering
- `text_fit()` — truncate text to fit width
- `wrap_text()` — multi-line text wrapping
- `rounded_panel()` — rounded rectangle (not needed in new design — no panel border)
- Color constants: `BACKGROUND`, `SURFACE`, `INK`, `MUTED`, `MUTED_DIM`, `FOOTER_BAR`
- Mode theme: `ASK` with `.accent`, `.accent_dim`, `.accent_soft`

### Helpers that may need addition

- **Circle fill** — a filled circle (not just rounded rectangle) for the icon background. Check if `rounded_panel` with equal width/height and radius=56 works, or use the display/theme primitives directly.
- **Centered text at specific Y** — the current code already does this pattern; just follow the existing `(WIDTH - text_width) // 2` pattern.

---

## Validation Checklist

After implementation:

- [ ] AskIdle shows centered sparkle icon in muted yellow circle with "Ask" heading and "Ask me anything..." subtitle in yellow
- [ ] AskListening shows brighter icon circle (optionally with glow), "Listening" heading, "Speak now..." in yellow
- [ ] AskThinking shows same-brightness icon circle (optionally rotated), "Thinking" heading, "Just a moment..." in muted gray
- [ ] AskReply shows left-aligned wrapped response text in muted color, no icon or heading
- [ ] HintBar text matches each state's Figma spec
- [ ] State transitions work: idle→listening→thinking→reply→listening (loop)
- [ ] Back from any state pops the screen
- [ ] Voice capture, transcription, and command matching all still work
- [ ] Auto-listen-on-entry behavior preserved
- [ ] Call/volume/music/mute commands still functional
- [ ] TTS responses still play
- [ ] Old `VoiceCommandsScreen` and `AIRequestsScreen` classes removed
- [ ] Old routes cleaned up in `router.py`
- [ ] `python -m compileall yoyopod tests` passes
- [ ] `uv run pytest -q` passes
- [ ] Existing tests in `test_screen_routing.py` updated for new route structure
