# Design Fidelity Workflow

Applies to: Figma-driven UI work for Whisplay, PIL fallback screens, and LVGL hardware scenes

## Goal

When implementing or refining Whisplay UI from Figma, preserve the product's existing screen model and make the real 240x280 device output match the design as closely as possible on actual hardware.

## Canonical Target

- Whisplay is the canonical small-screen target for this workflow: `240x280` portrait.
- Treat rounded display corners and edge clipping as real constraints. Leave visual safety margin at the top, sides, and footer.
- A screen is only "done" after it has been checked on the Pi, not just in local PIL output.

## Figma Intake Rules

- Prefer standard Figma Design links with `node-id=...`. A Figma Make link is acceptable only as a loose concept preview.
- Extract one runtime screen at a time. Do not try to reproduce an entire board as a single device screen.
- Map each Figma frame onto the existing YoyoPod information architecture and routes before changing code.
- Reuse the current navigation model. Do not introduce a second navigation system just because the Figma board is organized differently.
- If the Figma hint text conflicts with the real one-button behavior, keep the real behavior and update the copy to match the hardware interaction.

## Implementation Split

- Shared visual tokens belong in `src/yoyopod/ui/screens/theme.py`.
- PIL fallback rendering belongs in the Python screen implementations under `src/yoyopod/ui/screens/**`.
- LVGL screen lifecycle stays in `src/yoyopod/ui/screens/**/lvgl/*.py`.
- Native Whisplay scene parity belongs in:
  - `src/yoyopod/ui/lvgl_binding/binding.py`
  - `src/yoyopod/ui/lvgl_binding/native/lvgl_shim.c`
  - `src/yoyopod/ui/lvgl_binding/native/lvgl_shim.h`
- Raw LVGL layout logic should remain confined to the LVGL binding layer. Do not spread direct LVGL object code across unrelated app modules.

## Recommended Order Of Work

1. Extract the design intent from Figma:
   - identify layout
   - identify reusable components
   - identify colors, spacing, chips, cards, icons, and footer behavior
2. Fit the design to Whisplay constraints:
   - simplify dense layouts
   - preserve safe margins
   - shorten helper text if it clips on real hardware
3. Update shared theme primitives first.
4. Update the Python screen behavior and PIL fallback.
5. Update the LVGL view layer.
6. Update the native LVGL scene when hardware parity requires it.
7. Validate locally.
8. Sync to the Pi and validate on the device.

## Extraction Heuristics

- Start by identifying reusable primitives such as:
  - large icon cards
  - action buttons
  - person headers
  - status chips
  - footer or hint bars
  - page dots
- Normalize those primitives into YoyoPod theme helpers instead of duplicating one-off measurements in every screen.
- Use the Figma design language, but compress it aggressively for `240x280`.
- Prefer one strong focal element per screen. Avoid dashboard-style compositions on Whisplay.

## Hardware Validation Loop

For Whisplay UI work, the standard loop is:

1. Validate locally:
   ```bash
   uv run python scripts/quality.py ci
   ```
   For iterative UI work, run the most relevant focused tests if the full suite is unnecessary.
2. Commit and push the branch you want to validate:
   ```bash
   git branch --show-current
   git rev-parse HEAD
   ```
3. Validate the committed branch or exact SHA on the Pi:
   ```bash
   yoyopod remote validate --branch <branch> --sha <commit>
   ```
4. Capture output from the Pi:
   - single capture with `yoyopod remote screenshot`
5. Compare the captured result against Figma and adjust.

Use `yoyopod remote sync` only if the user explicitly wants a dirty-tree hardware check as a one-off debugging override.

## Screenshot Interpretation

- Shadow buffer screenshot: what the app tried to send to the display path.
- LVGL readback screenshot: what LVGL rendered internally.
- Real device photo: what the physical glass actually showed.

Use all three appropriately:

- Use shadow buffer for fast layout validation.
- Use LVGL readback when validating the native LVGL scene itself.
- Use a real device photo when checking rounded-corner safety, physical edge clipping, brightness, or suspected panel-transfer issues.

## Native Rebuild Rule

- If `src/yoyopod/ui/lvgl_binding/native/lvgl_shim.c`, `lvgl_shim.h`, `binding.py`, or LVGL config changes, the native shim must be rebuilt on the Pi before judging the hardware result.
- `yoyopod remote validate` and `yoyopod remote restart` may rebuild stale native shims automatically. Do not assume a stale Pi build reflects local code.

## Whisplay-Specific Acceptance Criteria

Before considering a Figma pass complete on Whisplay:

- the shared theme and the LVGL scene agree visually
- helper text fits within the footer safely
- status bar spacing is comfortable on real glass
- chips, dots, icons, and cards match the intended design hierarchy
- one-button hint text matches the actual interaction behavior
- a Pi screenshot or gallery has been captured after the final sync

## Commit And PR Hygiene

- Do not commit `temp/` screenshot artifacts.
- Keep gallery captures local unless the user explicitly asks to store them in-repo.
- In PR descriptions for design work, include both:
  - the visual areas changed
  - the validation steps used on the Pi
