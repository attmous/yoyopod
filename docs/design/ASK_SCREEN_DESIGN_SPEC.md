# Ask Screen Design Specification

**Status:** Design target for the unified Rust `Ask` experience
**Source:** Figma YoYoPod-Design, node `43:4677` (Ask section)
**Extracted:** 2026-04-10
**Target:** 240x280 Whisplay portrait display
**Rendering path:** Rust LVGL scene code in `device/ui/`

Use this file for intended interaction and visual design. For implementation
truth, trust the current Rust runtime and UI code under `device/runtime/`,
`device/speech/`, and `device/ui/`.

## Design Overview

The Figma design shows one unified Ask screen with four visual states. It is not
a submenu and it does not route to legacy Python voice/AI screens.

```
Ask scene
  idle       -> entry state, waiting for the user
  listening  -> speech capture is active
  thinking   -> transcript or command is being processed
  reply      -> response text is visible
```

| State | Figma Node | Key Visual |
|---|---|---|
| Idle | `43:5658` | Sparkle icon in muted circle, "Ask", "Ask me anything..." |
| Listening | `43:5694` | Same icon with yellow glow, "Listening", "Speak now..." |
| Thinking | `43:5730` | Rotated sparkle icon, "Thinking", "Just a moment..." |
| Reply | `43:5763` | Full-width text response area, no icon |

## Runtime Contract

- `device/runtime/` owns navigation, state composition, and worker event routing.
- `device/speech/` owns speech capture, transcript, command, and response events.
- `device/ui/` owns the Ask scene rendering and button-driven transitions.
- Python CLI validation may trigger Rust diagnostics, but it must not re-create
  Ask command routing or screen behavior in Python.

The Ask route should stay one screen. It may route out only for concrete side
effects such as starting a call, starting music, or returning to the previous
screen.

## Common Layout

All states share the 240x280 Whisplay frame:

```
+-----------------------------+ y=0
| StatusBar                   | render_header
+-----------------------------+ y=32
|                             |
| Content Area                | state-specific rendering
|                             |
+-----------------------------+ y=248
| HintBar                     | render_footer
+-----------------------------+ y=280
```

- Background: `#2A2D35`
- StatusBar: `render_header` with Ask mode and time visible
- HintBar: `render_footer` with state-specific button help

## State Details

### Idle

- Large centered sparkle icon in a muted yellow circle.
- Heading: `Ask`
- Subtitle: `Ask me anything...`
- One-button hint: `2x Tap = Ask | Hold = Back`
- Transition: select/double-tap moves to `listening`; back/hold pops.

### Listening

- Same layout as idle, but the icon circle is brighter and may glow.
- Heading: `Listening`
- Subtitle: `Speak now...`
- One-button hint: `Speaking... | Hold = Cancel`
- Transition: capture complete moves to `thinking`; failure moves to `reply`
  with an error message; back cancels.

### Thinking

- Centered icon layout with muted subtitle.
- Heading: `Thinking`
- Subtitle: `Just a moment...`
- Hint: `Processing...`
- Transition: transcript or command result moves to `reply`; back cancels.

### Reply

- Left-aligned response text block.
- No icon circle and no heading.
- Text color: `#B4B7BE`
- One-button hint: `2x Tap = Ask Again | Hold = Back`
- Transition: select/double-tap starts another ask; back pops.

## Visual Tokens

| Token | Hex | RGB | Usage |
|---|---|---|---|
| Background | `#2A2D35` | `(42, 45, 53)` | Screen background |
| Footer bar | `#1F2127` | `(31, 33, 39)` | HintBar background |
| Ink | `#FFFFFF` | `(255, 255, 255)` | Headings |
| Muted | `#B4B7BE` | `(180, 183, 190)` | Reply text |
| Muted dim | `#7A7D84` | `(122, 125, 132)` | Hint text, thinking subtitle |
| Ask accent | `#FFD000` | `(255, 208, 0)` | Icon and active subtitle |
| Idle circle | blended accent | approx `(74, 69, 45)` | 15% accent over background |
| Listening circle | blended accent | approx `(95, 86, 48)` | 25% accent over background |

## Typography

| Element | Font | Weight | Size |
|---|---|---|---|
| Heading | Fredoka | SemiBold | 20px |
| Idle/listening subtitle | Inter | SemiBold | 14px |
| Thinking subtitle | Inter | Regular | 14px |
| Reply text | Inter | Regular | 14px |
| HintBar | Inter | Regular | 12px |
| StatusBar time | Inter | Medium | 11px |

## Implementation Notes

- Reuse Rust theme helpers for header, footer, icon drawing, text fitting, and
  wrapping.
- Add or reuse a filled-circle primitive for the icon background.
- Keep state names stable enough for runtime snapshot/debug output.
- Exact sparkle rotation in `thinking` is nice to have; state, layout, and color
  parity matter more than rotation precision on the small display.
- Voice command behavior belongs in the Rust speech/runtime stack. The UI scene
  should render state and emit user intent, not own command parsing.

## Validation Checklist

- Ask idle, listening, thinking, and reply states render with the expected
  layout, copy, and colors on Whisplay.
- Button transitions cover idle -> listening -> thinking -> reply -> listening.
- Back/hold exits or cancels from every state.
- Speech capture, transcription, command routing, and response text flow through
  the Rust runtime stack.
- Call, volume, music, mute, and screen-read command behaviors still work.
- `cargo test --manifest-path device/Cargo.toml --workspace --locked` passes for
  affected Rust code.
- `yoyopod remote validate --branch <branch> --sha <commit>` proves the target
  hardware flow when the change touches runtime behavior.
