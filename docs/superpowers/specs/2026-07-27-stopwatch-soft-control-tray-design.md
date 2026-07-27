# Stopwatch Soft Control Tray Design

Date: 2026-07-27  
Status: Approved and implemented

## Objective

Refine the Stopwatch screen so its controls feel playful and attractive while remaining unmistakably part of YoYoPod. The approved direction is **Soft Control Tray**: a quiet translucent tray groups the actions, phase-aware colors make each state obvious, and the timer remains the dominant element.

This began as a visual refinement. Stopwatch timing, navigation, persistence, and process architecture remain unchanged; physical-device feedback adds one targeted input correction so a single tap activates the sole Start or Pause action.

## Locked Device Chrome

The status bar and bottom destination deck are immutable for this work.

- Keep the top status bar at screen rows `0..24` unchanged.
- Keep the bottom destination deck at screen rows `228..280` unchanged.
- Do not change their components, layout roles, theme roles, SVG assets, icon order, selected Stopwatch pill, visibility, or navigation behavior.
- Do not modify `components/screens/chrome.rs`, `components/widgets/status_bar.rs`, or `components/widgets/deck_bar.rs`.
- Restrict all new visual elements to the Stopwatch stage between screen rows `24..228`.

The existing four visible destination icons remain exactly as rendered today.
All screen-row ranges in this document are half-open: the start row is included and the end row is excluded.

## Visual Direction

### Palette

Use existing YoYoPod tokens wherever possible so light and dark themes stay coherent.

| Role | Light value | Purpose |
|---|---:|---|
| Stopwatch stage | `#E7E5F7` | Existing periwinkle stage; unchanged |
| Tray and phase surfaces | `#FCE6D2` at opacity `112` | Existing surface token; soft grouping without a card-heavy look |
| Start / Resume | `#78D5D0` | Teal positive action |
| Pause | `#FFB45C` | Warm amber active-timing control |
| Reset | `#FDE2D8` | Quiet coral secondary/destructive action |
| Running indicator | `#F37B67` | Small static live-state dot |
| Primary ink | `#1B1B1F` | Timer, icons, labels, and focus outline |

Custom accent colors remain accents in dark mode. Surface, stage, and ink values use the existing semantic dark-theme substitution.

### Typography

- Keep the centered Montserrat timer readout at 40 px below one hour.
- Preserve the current `MM:SS.t` and `HH:MM:SS` formats.
- Use a compact 12 px Montserrat phase label: `Ready`, `Running`, or `Paused`.
- Use the existing button icon assets and 12 px Montserrat action labels.
- Avoid novelty typefaces, outlined text, and decorative copy.

### Geometry

All coordinates are screen-relative on the canonical 240x280 Whisplay panel.

| Element | Bounds | Notes |
|---|---|---|
| Stopwatch stage | `x=0, y=24, w=240, h=204` | Only mutable visual region |
| Timer readout | `x=12, y=52, w=216, h=58` | Large centered focal element |
| Phase chip | `x=76, y=108, w=88, h=22` | Fixed centered surface for all phases |
| Control tray | `x=18, y=142, w=204, h=72` | Rounded shared surface |
| Single action | `x=57, y=149, w=126, h=58` | Ready and Running |
| Paused Resume | `x=24, y=149, w=92, h=58` | First action |
| Paused Reset | `x=124, y=149, w=92, h=58` | Second action; 8 px gap |
| Focus dots | `x=94, y=218, w=52, h=8` | Preserve existing one/two-dot semantics |

The tray uses a 24 px outer radius. Action tiles use an 18 px radius. Focused actions receive the existing 2 px ink outline with a 2 px pad. There are no drop shadows, thick arcade borders, stickers, gradients, or changes to the surrounding chrome.

## State Design

### Ready

- Display `00:00.0`.
- Show phase `Ready`.
- Center one teal Start action inside the tray.
- Start is focused and uses the standard ink outline.
- Show one active focus dot.

### Running

- Continue updating the timer only when the displayed tenth changes.
- Show phase `Running` with a small static coral dot.
- Center one amber Pause action inside the tray.
- Pause is focused and uses the standard ink outline.
- Show one active focus dot.

The running dot does not blink. It introduces no new animation or redraw cadence.

### Paused

- Freeze the current timer display.
- Show phase `Paused`.
- Show teal Resume and soft-coral Reset actions side by side.
- Resume is initially focused.
- A single tap transfers the focus outline and active dot.
- A double tap activates the focused action.

## Interaction Contract

Existing behavior remains authoritative:

- Ready exposes Start.
- Running exposes Pause.
- Paused exposes Resume and Reset.
- A single tap activates Start or Pause when it is the only visible action.
- Single tap changes the focused paused action.
- Double tap activates the focused paused action.
- Reset is available only while paused.
- Stopwatch resets whenever navigation leaves the screen, including Home, Back, incoming-call preemption, or system-error preemption.
- Stopwatch state never persists or runs off-screen.
- Accessibility labels remain `Start`, `Pause`, `Resume`, and `Reset`.

## Component and Data Design

The existing application-owned `StopwatchPhase` remains the source of truth. Add a small scene-facing phase value to `StopwatchModel` so rendering never infers state from localized button text.

The Stopwatch widget gains dedicated semantic roles:

- `stopwatch_phase`
- `stopwatch_phase_dot`
- `stopwatch_phase_label`
- `stopwatch_control_tray`
- `stopwatch_action_primary`
- `stopwatch_action_pause`
- `stopwatch_action_reset`
- `stopwatch_action_icon`
- `stopwatch_action_label`

These roles isolate the new styling from the generic `button` component used by other screens. The widget constructs either one centered action or two equal actions according to the existing action list and phase.

Start and Resume use `stopwatch_action_primary`, Pause uses `stopwatch_action_pause`, and Reset uses `stopwatch_action_reset`. Add corresponding entries to `layouts.ron` and `theme.ron`, and register every new role in the renderer's required-role coverage. Because selected theme styles replace rather than merge with base styles, each of the three selected action assets must repeat its complete fill, opacity, radius, text, and outline properties.

The generic LVGL scene renderer remains responsible for creating and styling objects. No new C/LVGL controller, protocol schema, worker domain, cross-process intent, or icon-generator asset is required.

## Rendering and Dirty Regions

- Phase or action changes request the normal stage/frame update already produced by input handling.
- Running timer ticks continue to use the existing partial Stopwatch timer dirty region.
- The phase chip, live dot, tray, buttons, status bar, and bottom deck do not redraw on each tenth.
- If the timer moves upward, update `STOPWATCH_TIMER_DIRTY_REGION` so it covers the new readout bounds and nothing else.
- No ambient animation is added.

## Failure Prevention

- Required layout and theme role validation must reject missing Stopwatch assets at startup.
- Required selected-theme coverage must include all three Stopwatch action roles, preventing another focus-time worker crash.
- The targeted Stopwatch input branch activates only when exactly one action is visible; the two-action Paused focus path and every other screen retain the existing behavior.
- Light and dark theme tests must verify legible tray, labels, action fills, and focus outlines.

## Testing

### Automated

- Widget tests for Ready, Running, and Paused element trees.
- Assert one-action and two-action geometry, labels, icon roles, phase labels, running-dot visibility, focus state, and focus-dot counts.
- Assert every Stopwatch-stage element stays within rows `24..228`.
- Asset coverage tests for all new layout, theme, and selected-theme roles.
- Theme resolver tests for focused Stopwatch actions in light and dark modes.
- Existing stopwatch timing, pause/resume/reset, drift, formatting, accessibility, reset-on-exit, and partial-redraw tests must remain green.
- Existing deck sliding, status bar, bottom icon, and route tests must remain unchanged and green.
- Run formatting, icon-generator `--check`, locked protocol/UI tests, and the full locked device workspace check.

### CI and Hardware

- Commit and push the feature branch.
- Deploy only the exact successful `yoyopod-rust-device-arm64-<sha>` CI artifact.
- Use the native Whisplay/LVGL protocol check to render Ready, Running, and Paused.
- Capture an LVGL readback of each state.
- Verify the top rows and bottom deck are visually unchanged from the pre-redesign capture.
- Verify the service remains active with every worker alive after the check.
- Exercise the real side button to confirm focus transfer and activation on physical glass.

## Non-Goals

- No top-bar changes.
- No bottom-icon or destination-deck changes.
- No Stopwatch timing or navigation changes.
- No new animation.
- No new or regenerated icons.
- No Flashlight changes.
- No alarms, dashboard, backend, or protocol work.
