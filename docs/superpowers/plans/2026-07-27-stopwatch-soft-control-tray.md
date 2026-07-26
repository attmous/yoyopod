# Stopwatch Soft Control Tray Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Stopwatch stage's generic action buttons with the approved phase-aware Soft Control Tray while preserving all existing timing, input, top-bar, and bottom-deck behavior.

**Architecture:** Keep `application::state::StopwatchPhase` as the runtime source of truth and map it into a small scene-facing `StopwatchVisualPhase` carried by `StopwatchModel`. The existing generic scene renderer continues to render a declarative Stopwatch element tree; dedicated layout and theme roles provide phase, tray, and semantic action styling without changing shared chrome or introducing a native controller.

**Tech Stack:** Rust 2021, YoYoPod scene graph, LVGL 9.5.0 FFI, RON layout/theme assets, locked Cargo workspace.

## Global Constraints

- Keep the top status bar at screen rows `0..24` unchanged.
- Keep the bottom destination deck at screen rows `228..280` unchanged.
- Do not modify `device/ui/src/components/screens/chrome.rs`, `device/ui/src/components/widgets/status_bar.rs`, or `device/ui/src/components/widgets/deck_bar.rs`.
- Do not change destination icons, icon generation, icon order, selected Stopwatch pill, visibility, or navigation behavior.
- Restrict Stopwatch visual elements to screen rows `24..228`.
- Preserve Stopwatch timing, input, reset-on-exit, accessibility, and partial-update cadence.
- Add no protocol schema, worker domain, cross-process intent, animation, Flashlight change, or alarm work.

---

### Task 1: Carry an explicit scene-facing Stopwatch phase

**Files:**
- Modify: `device/ui/src/scene/deck.rs`
- Modify: `device/ui/src/scene/mod.rs`
- Modify: `device/ui/src/components/screens/mod.rs`
- Modify: `device/ui/src/components/screens/stopwatch.rs`
- Modify: `device/ui/src/application/runtime.rs`
- Test: `device/ui/src/components/widgets/stopwatch.rs`

**Interfaces:**
- Consumes: `application::state::StopwatchPhase::{Idle, Running, Paused}`.
- Produces: `scene::StopwatchVisualPhase::{Ready, Running, Paused}` and `StopwatchModel.phase: StopwatchVisualPhase`.

- [ ] **Step 1: Write the failing phase-model widget test**

Add imports for `StopwatchVisualPhase` and construct three models. Assert that the first child carrying role `stopwatch_phase_label` contains the literal phase text and that a `stopwatch_phase_dot` exists only for `Running`.

```rust
#[test]
fn phase_label_and_live_dot_follow_the_explicit_visual_phase() {
    for (phase, expected_label, expected_dot_count) in [
        (StopwatchVisualPhase::Ready, "Ready", 0),
        (StopwatchVisualPhase::Running, "Running", 1),
        (StopwatchVisualPhase::Paused, "Paused", 0),
    ] {
        let element = stopwatch(&StopwatchModel {
            display: "00:12.3".to_string(),
            phase,
            actions: vec![ButtonModel {
                title: "Pause".to_string(),
                icon_key: "pause_sm".to_string(),
            }],
            focus_index: 0,
        });

        assert_eq!(
            descendants_with_role(&element, roles::STOPWATCH_PHASE_LABEL)[0]
                .props
                .text
                .as_deref(),
            Some(expected_label)
        );
        assert_eq!(
            descendants_with_role(&element, roles::STOPWATCH_PHASE_DOT).len(),
            expected_dot_count
        );
    }
}
```

The production change caught by this test is dropping or incorrectly mapping the explicit phase value, which would show the wrong label or live indicator despite correct actions.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
& "$env:USERPROFILE\.cargo\bin\cargo.exe" test --manifest-path device\Cargo.toml -p yoyopod-ui --locked phase_label_and_live_dot_follow_the_explicit_visual_phase
```

Expected: compilation fails because `StopwatchVisualPhase`, `StopwatchModel.phase`, and the phase roles do not exist.

- [ ] **Step 3: Add the minimal phase model and runtime mapping**

In `device/ui/src/scene/deck.rs`, add:

```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StopwatchVisualPhase {
    Ready,
    Running,
    Paused,
}

impl StopwatchVisualPhase {
    pub const fn label(self) -> &'static str {
        match self {
            Self::Ready => "Ready",
            Self::Running => "Running",
            Self::Paused => "Paused",
        }
    }
}
```

Add `pub phase: StopwatchVisualPhase` to `StopwatchModel`, and re-export the enum from `scene/mod.rs`.

Extend `components::screens::scene_for_screen` and `components::screens::stopwatch::scene` with a `StopwatchVisualPhase` argument. In `UiRuntime::scene_graph`, map runtime state exhaustively:

```rust
let stopwatch_phase = match self.stopwatch.phase {
    super::state::StopwatchPhase::Idle => StopwatchVisualPhase::Ready,
    super::state::StopwatchPhase::Running => StopwatchVisualPhase::Running,
    super::state::StopwatchPhase::Paused => StopwatchVisualPhase::Paused,
};
```

Pass `stopwatch_phase` into the screen scene and then into `StopwatchModel`.

- [ ] **Step 4: Add the phase element skeleton and verify GREEN**

Add these role constants in `device/ui/src/scene/roles.rs`:

```rust
pub(crate) const STOPWATCH_PHASE: &str = "stopwatch_phase";
pub(crate) const STOPWATCH_PHASE_DOT: &str = "stopwatch_phase_dot";
pub(crate) const STOPWATCH_PHASE_LABEL: &str = "stopwatch_phase_label";
```

In `components/widgets/stopwatch.rs`, add a `stopwatch_phase` helper that creates a phase container, conditionally creates the live dot for `Running`, and always creates the phase label from `model.phase.label()`.

Run the focused test again. Expected: PASS.

- [ ] **Step 5: Commit the phase-model slice**

```powershell
git add device/ui/src/scene/deck.rs device/ui/src/scene/mod.rs device/ui/src/scene/roles.rs device/ui/src/components/screens/mod.rs device/ui/src/components/screens/stopwatch.rs device/ui/src/components/widgets/stopwatch.rs device/ui/src/application/runtime.rs
git commit -m "refactor(ui): expose stopwatch visual phase"
```

### Task 2: Build the declarative Soft Control Tray element tree

**Files:**
- Modify: `device/ui/src/components/widgets/stopwatch.rs`
- Modify: `device/ui/src/components/screens/stopwatch.rs`
- Test: `device/ui/src/components/widgets/stopwatch.rs`

**Interfaces:**
- Consumes: `StopwatchModel { display, phase, actions, focus_index }`.
- Produces: a panel containing readout, phase chip, tray, one or two semantic action tiles, and scene-local focus dots.

- [ ] **Step 1: Write failing Ready and Running tree tests**

Add a recursive test helper:

```rust
fn descendants_with_role<'a>(element: &'a Element, role: &str) -> Vec<&'a Element> {
    let mut found = Vec::new();
    if element.role == Some(role) {
        found.push(element);
    }
    for child in &element.children {
        found.extend(descendants_with_role(child, role));
    }
    found
}
```

Add a table-driven test asserting Ready uses one selected primary action and Running uses one selected pause action:

```rust
#[test]
fn ready_and_running_use_one_centered_phase_aware_action() {
    for (phase, title, action_role) in [
        (
            StopwatchVisualPhase::Ready,
            "Start",
            roles::STOPWATCH_ACTION_PRIMARY,
        ),
        (
            StopwatchVisualPhase::Running,
            "Pause",
            roles::STOPWATCH_ACTION_PAUSE,
        ),
    ] {
        let element = stopwatch(&StopwatchModel {
            display: "00:00.0".to_string(),
            phase,
            actions: vec![ButtonModel {
                title: title.to_string(),
                icon_key: if title == "Pause" { "pause_sm" } else { "play_sm" }.to_string(),
            }],
            focus_index: 0,
        });
        let actions = descendants_with_role(&element, action_role);
        assert_eq!(actions.len(), 1);
        assert_eq!(actions[0].layout, Layout::Absolute { x: 39, y: 7, w: 126, h: 58 });
        assert_eq!(actions[0].props.selected, Some(true));
        assert_eq!(descendants_with_role(&element, roles::CURSOR_DOT).len(), 1);
    }
}
```

The `x=39` action coordinate is relative to the `x=18` tray; its screen coordinate is `57`, matching the approved design.

- [ ] **Step 2: Write the failing Paused tree test**

Replace the old generic-button test with assertions that Resume and Reset use distinct semantic roles, have relative tray coordinates `x=6` and `x=106`, preserve the 8 px screen gap, expose the correct icon/label roles, and create two focus dots with only the selected index active.

```rust
#[test]
fn paused_state_uses_two_semantic_actions_and_two_focus_dots() {
    let element = stopwatch(&StopwatchModel {
        display: "00:12.3".to_string(),
        phase: StopwatchVisualPhase::Paused,
        actions: vec![
            ButtonModel {
                title: "Resume".to_string(),
                icon_key: "play_sm".to_string(),
            },
            ButtonModel {
                title: "Reset".to_string(),
                icon_key: "reset_sm".to_string(),
            },
        ],
        focus_index: 1,
    });

    let resume = descendants_with_role(&element, roles::STOPWATCH_ACTION_PRIMARY)[0];
    let reset = descendants_with_role(&element, roles::STOPWATCH_ACTION_RESET)[0];
    assert_eq!(resume.layout, Layout::Absolute { x: 6, y: 7, w: 92, h: 58 });
    assert_eq!(reset.layout, Layout::Absolute { x: 106, y: 7, w: 92, h: 58 });
    assert_eq!(resume.props.selected, Some(false));
    assert_eq!(reset.props.selected, Some(true));
    assert_eq!(
        descendants_with_role(reset, roles::STOPWATCH_ACTION_ICON)[0]
            .props
            .icon_key
            .as_deref(),
        Some("reset_sm")
    );
    let dots = descendants_with_role(&element, roles::CURSOR_DOT);
    assert_eq!(dots.len(), 2);
    assert_eq!(dots[0].props.selected, Some(false));
    assert_eq!(dots[1].props.selected, Some(true));
}
```

The production changes caught are accidental reuse of the generic button theme, wrong action order/spacing, wrong focus state, and missing two-action focus feedback.

- [ ] **Step 3: Run the widget tests and verify RED**

Run:

```powershell
& "$env:USERPROFILE\.cargo\bin\cargo.exe" test --manifest-path device\Cargo.toml -p yoyopod-ui --locked components::widgets::stopwatch::tests
```

Expected: the tests fail because the semantic action/tray roles and approved element geometry are absent.

- [ ] **Step 4: Implement the minimal element tree**

Add constants for:

```rust
pub(crate) const STOPWATCH_CONTROL_TRAY: &str = "stopwatch_control_tray";
pub(crate) const STOPWATCH_ACTION_PRIMARY: &str = "stopwatch_action_primary";
pub(crate) const STOPWATCH_ACTION_PAUSE: &str = "stopwatch_action_pause";
pub(crate) const STOPWATCH_ACTION_RESET: &str = "stopwatch_action_reset";
pub(crate) const STOPWATCH_ACTION_ICON: &str = "stopwatch_action_icon";
pub(crate) const STOPWATCH_ACTION_LABEL: &str = "stopwatch_action_label";
```

Build the tree with these panel-relative bounds:

```text
panel             (0, 24, 240, 204)
readout           role layout (12, 28, 216, 58)
phase chip        role layout (76, 84, 88, 22)
control tray      role layout (18, 118, 204, 72)
single action     tray-relative (39, 7, 126, 58)
paused Resume     tray-relative (6, 7, 92, 58)
paused Reset      tray-relative (106, 7, 92, 58)
focus dots        panel-relative (94, 194, 52, 8)
```

For each action, use `STOPWATCH_ACTION_ICON` and `STOPWATCH_ACTION_LABEL` children with action-relative bounds that center the 24 px icon and label for the action's actual width:

```rust
.child(
    Element::new(ElementKind::Image, Some(roles::STOPWATCH_ACTION_ICON))
        .absolute((action_width - 24) / 2, 7, 24, 24)
        .icon(&action.icon_key),
)
.child(
    label(roles::STOPWATCH_ACTION_LABEL)
        .absolute(8, 36, action_width - 16, 16)
        .text(&action.title),
)
```

For the phase chip, use `(14, 8, 6, 6)` for the Running dot and `(25, 3, 49, 16)` for the Running label. Ready and Paused omit the dot and use `(8, 3, 72, 16)` for the centered label.

Choose the semantic action role from the literal action title:

```rust
let action_role = match action.title.as_str() {
    "Pause" => roles::STOPWATCH_ACTION_PAUSE,
    "Reset" => roles::STOPWATCH_ACTION_RESET,
    "Start" | "Resume" => roles::STOPWATCH_ACTION_PRIMARY,
    _ => roles::STOPWATCH_ACTION_PRIMARY,
};
```

Build the focus dots directly in the Stopwatch widget using existing `cursor_dots` and `cursor_dot` roles. Set `Scene.cursor` to `None` in `components/screens/stopwatch.rs` so the generic global cursor is not duplicated.

- [ ] **Step 5: Add and pass the glass-safe bounds test**

Recursively accumulate parent and child absolute layouts and assert every visible Stopwatch widget rectangle satisfies `y >= 24` and `y + h <= 228`, with `x >= 0` and `x + w <= 240`.

Run all Stopwatch widget tests. Expected: PASS.

- [ ] **Step 6: Commit the widget-tree slice**

```powershell
git add device/ui/src/components/widgets/stopwatch.rs device/ui/src/components/screens/stopwatch.rs device/ui/src/scene/roles.rs
git commit -m "feat(ui): build stopwatch soft control tray"
```

### Task 3: Add exact layout and theme assets with complete focus styles

**Files:**
- Modify: `device/ui/assets/layouts.ron`
- Modify: `device/ui/assets/theme.ron`
- Modify: `device/ui/src/renderer/assets.rs`
- Modify: `device/ui/src/renderer/styling/theme.rs`
- Modify: `device/ui/src/theme.rs`
- Test: `device/ui/src/renderer/assets.rs`
- Test: `device/ui/src/renderer/styling/theme.rs`

**Interfaces:**
- Consumes: the nine new Stopwatch roles from Tasks 1 and 2.
- Produces: complete light/dark-resolvable base styles plus selected styles for primary, pause, and reset actions.

- [ ] **Step 1: Write the failing layout/palette contract test**

In `renderer/assets.rs`, add `stopwatch_soft_control_tray_matches_the_approved_geometry_and_palette`. Assert the exact panel-relative asset geometry, and assert:

```rust
assert_eq!(theme(&themes, roles::STOPWATCH_CONTROL_TRAY).fill_rgb, Some(0xFCE6D2));
assert_eq!(theme(&themes, roles::STOPWATCH_CONTROL_TRAY).opacity, Some(112));
assert_eq!(theme(&themes, roles::STOPWATCH_CONTROL_TRAY).radius, 24);
assert_eq!(theme(&themes, roles::STOPWATCH_ACTION_PRIMARY).fill_rgb, Some(0x78D5D0));
assert_eq!(theme(&themes, roles::STOPWATCH_ACTION_PAUSE).fill_rgb, Some(0xFFB45C));
assert_eq!(theme(&themes, roles::STOPWATCH_ACTION_RESET).fill_rgb, Some(0xFDE2D8));
assert_eq!(theme(&themes, roles::STOPWATCH_PHASE_DOT).fill_rgb, Some(0xF37B67));
```

For each action role, assert the selected asset repeats the same `fill_rgb`, `opacity=255`, `radius=18`, and `text_rgb=0x1B1B1F`, plus `outline_rgb=0x1B1B1F`, `outline_width=2`, and `outline_pad=2`.

The production changes caught are incomplete selected styles (the previous crash class), wrong semantic fills, or geometry drifting into device chrome.

- [ ] **Step 2: Write the failing light/dark resolver test**

Replace the generic Stopwatch `roles::BUTTON` resolver assertion with a table over the three semantic action roles. In both light and dark schemes assert that selected resolution succeeds, retains the accent fill and opacity, uses radius 18, and supplies a 2 px focus outline. Also assert tray/phase surfaces resolve to `SURFACE_0_LIGHT` in light and `SURFACE_0_DARK` in dark, while action icon and label foregrounds resolve to `INK_ON_ACCENT` in dark.

- [ ] **Step 3: Run the focused asset and resolver tests and verify RED**

Run:

```powershell
& "$env:USERPROFILE\.cargo\bin\cargo.exe" test --manifest-path device\Cargo.toml -p yoyopod-ui --locked stopwatch_soft_control_tray_matches_the_approved_geometry_and_palette
& "$env:USERPROFILE\.cargo\bin\cargo.exe" test --manifest-path device\Cargo.toml -p yoyopod-ui --locked focused_stopwatch_actions_preserve_semantic_surfaces_in_both_themes
```

Expected: failure because the required assets and semantic foreground policy are missing.

- [ ] **Step 4: Add all required layout and base-theme roles**

Add all nine roles to `required_layout_roles`; they automatically become required base-theme roles. Add the three semantic action roles to `required_selected_theme_roles`.

Add RON layout roles using panel-relative geometry:

```ron
(role: "stopwatch_panel", x: 0, y: 24, width: 240, height: 204),
(role: "stopwatch_readout", x: 12, y: 28, width: 216, height: 58),
(role: "stopwatch_phase", x: 76, y: 84, width: 88, height: 22),
(role: "stopwatch_phase_dot", x: 14, y: 8, width: 6, height: 6),
(role: "stopwatch_phase_label", x: 8, y: 3, width: 72, height: 16),
(role: "stopwatch_control_tray", x: 18, y: 118, width: 204, height: 72),
(role: "stopwatch_action_primary", x: 39, y: 7, width: 126, height: 58),
(role: "stopwatch_action_pause", x: 39, y: 7, width: 126, height: 58),
(role: "stopwatch_action_reset", x: 106, y: 7, width: 92, height: 58),
(role: "stopwatch_action_icon", x: 34, y: 7, width: 24, height: 24),
(role: "stopwatch_action_label", x: 8, y: 36, width: 76, height: 16),
```

Add base theme roles with tray/phase fill `0xFCE6D2` at opacity `112`, tray radius `24`, phase radius `11`, action radius `18`, the approved action fills, coral running dot, and ink foregrounds. Add complete selected roles for primary, pause, and reset.

- [ ] **Step 5: Add semantic dark-theme foreground policy and verify GREEN**

Add `STOPWATCH_ACTION_ICON` and `STOPWATCH_ACTION_LABEL` to `foreground_policy(...).primary_on_accent` so their stored `0x1B1B1F` ink stays dark on the custom teal/amber/coral accent fills in dark mode.

Run both focused tests, then:

```powershell
& "$env:USERPROFILE\.cargo\bin\cargo.exe" test --manifest-path device\Cargo.toml -p yoyopod-ui --locked shipped_layout_and_theme_cover_every_runtime_role
```

Expected: all PASS, proving missing base or selected assets fail before hardware rendering.

- [ ] **Step 6: Commit the asset slice**

```powershell
git add device/ui/assets/layouts.ron device/ui/assets/theme.ron device/ui/src/renderer/assets.rs device/ui/src/renderer/styling/theme.rs device/ui/src/theme.rs
git commit -m "feat(ui): style stopwatch soft control tray"
```

### Task 4: Apply Stopwatch-specific LVGL tuning and preserve partial redraws

**Files:**
- Modify: `device/ui/src/renderer/lvgl/ffi.rs`
- Modify: `device/ui/src/renderer/styling/tuning/base.rs`
- Modify: `device/ui/src/renderer/styling/tuning/text.rs`
- Modify: `device/ui/src/application/runtime.rs`
- Test: `device/ui/src/application/runtime.rs`

**Interfaces:**
- Consumes: the new role element tree and already-enabled LVGL Montserrat 40 font.
- Produces: centered 40 px readout, centered 12 px phase/action labels, centered action icons, zero-padding rounded surfaces, and the exact timer-only dirty region.

- [ ] **Step 1: Change the dirty-region expectation first and verify RED**

Update `stopwatch_requests_only_timer_region_when_visible_text_changes` to expect the approved readout rectangle:

```rust
assert_eq!(
    frame.dirty_region,
    Some(DirtyRegion {
        x: 12,
        y: 52,
        w: 216,
        h: 58,
    })
);
```

Run the test. Expected: FAIL because production still returns `y=60`.

- [ ] **Step 2: Update only the Stopwatch timer dirty region and verify GREEN**

Change `STOPWATCH_TIMER_DIRTY_REGION.y` from `60` to `52`. Re-run the focused test and the existing irregular-tick cadence test. Expected: PASS with timer-only ticks still producing no full-frame update.

- [ ] **Step 3: Add the LVGL font and role tuning**

Declare the already-enabled LVGL font in `renderer/lvgl/ffi.rs`:

```rust
pub static lv_font_montserrat_40: lv_font_t;
```

Keep `WATCH_TIME` on Montserrat 48 and move `STOPWATCH_READOUT` into its own `text.rs` arm using Montserrat 40, clip mode, and centered text. Add phase/action labels to the Montserrat 12 centered arm and center `STOPWATCH_ACTION_ICON` with `lv_image_set_inner_align`.

In `base.rs`, apply zero padding and disabled scrollbars to phase, tray, semantic actions, live dot, and focus-dot containers so RON bounds map exactly to physical pixels.

- [ ] **Step 4: Run the complete focused Stopwatch suite**

Run:

```powershell
& "$env:USERPROFILE\.cargo\bin\cargo.exe" test --manifest-path device\Cargo.toml -p yoyopod-ui --locked stopwatch
```

Expected: all Stopwatch timing, accessibility, reset, widget, asset, resolver, and dirty-region tests PASS.

- [ ] **Step 5: Commit the renderer slice**

```powershell
git add device/ui/src/renderer/lvgl/ffi.rs device/ui/src/renderer/styling/tuning/base.rs device/ui/src/renderer/styling/tuning/text.rs device/ui/src/application/runtime.rs
git commit -m "fix(ui): tune stopwatch tray rendering"
```

### Task 5: Validate immutable chrome and the locked device workspace

**Files:**
- Modify: `docs/superpowers/specs/2026-07-27-stopwatch-soft-control-tray-design.md`
- Verify unchanged: `device/ui/src/components/screens/chrome.rs`
- Verify unchanged: `device/ui/src/components/widgets/status_bar.rs`
- Verify unchanged: `device/ui/src/components/widgets/deck_bar.rs`

**Interfaces:**
- Consumes: completed Soft Control Tray implementation.
- Produces: a clean, formatted, fully validated feature branch ready for review and exact-artifact CI.

- [ ] **Step 1: Mark the design spec implemented**

Change the spec status line to:

```markdown
Status: Approved and implemented
```

- [ ] **Step 2: Format and prove locked chrome files are untouched**

Run:

```powershell
& "$env:USERPROFILE\.cargo\bin\cargo.exe" fmt --manifest-path device\Cargo.toml --all
git diff --exit-code 37508bad -- device/ui/src/components/screens/chrome.rs device/ui/src/components/widgets/status_bar.rs device/ui/src/components/widgets/deck_bar.rs device/ui/assets/icons
```

Expected: formatting succeeds and `git diff --exit-code` returns 0.

- [ ] **Step 3: Run icon and focused locked tests**

Run:

```powershell
& "$env:USERPROFILE\.cargo\bin\cargo.exe" run --manifest-path device\ui\tools\icon-gen\Cargo.toml --locked -- --check
& "$env:USERPROFILE\.cargo\bin\cargo.exe" test --manifest-path device\Cargo.toml -p yoyopod-protocol -p yoyopod-ui --locked
```

Expected: icon generator reports generated assets are current; protocol/UI tests pass.

- [ ] **Step 4: Run the full locked workspace check**

Run:

```powershell
& "$env:USERPROFILE\.cargo\bin\cargo.exe" check --manifest-path device\Cargo.toml --workspace --locked
```

Expected: every device crate checks successfully.

- [ ] **Step 5: Commit the completed implementation state**

```powershell
git add docs/superpowers/specs/2026-07-27-stopwatch-soft-control-tray-design.md docs/superpowers/plans/2026-07-27-stopwatch-soft-control-tray.md device/ui
git commit -m "feat(ui): finish stopwatch soft control tray"
```

### Task 6: Review, publish, and prepare exact-artifact deployment

**Files:**
- Review: all changes from `37508bad..HEAD`
- Update: existing PR for `codex/stopwatch-flashlight`

**Interfaces:**
- Consumes: verified clean branch.
- Produces: reviewed commits pushed to the existing PR and a CI artifact identified by exact commit SHA.

- [ ] **Step 1: Perform Rust and general code review**

Review the diff for correctness, crash safety, theme completeness, screen bounds, non-Stopwatch regressions, and unnecessary changes. Fix each actionable finding test-first and rerun the affected focused tests.

- [ ] **Step 2: Run verification immediately before publishing**

Repeat:

```powershell
& "$env:USERPROFILE\.cargo\bin\cargo.exe" test --manifest-path device\Cargo.toml -p yoyopod-protocol -p yoyopod-ui --locked
& "$env:USERPROFILE\.cargo\bin\cargo.exe" check --manifest-path device\Cargo.toml --workspace --locked
git status --short
```

Expected: both Rust commands succeed and the worktree is clean.

- [ ] **Step 3: Push and update the existing PR**

```powershell
git push origin codex/stopwatch-flashlight
gh pr view 478 --json url,headRefName,state
```

Expected: PR `#478` points at `codex/stopwatch-flashlight` and includes the new commit SHA.

- [ ] **Step 4: Wait for exact-commit CI and report the artifact**

Identify the successful CI run for `git rev-parse HEAD` and record artifact name:

```text
yoyopod-rust-device-arm64-<full-commit-sha>
```

Do not deploy a local or stale binary.

- [ ] **Step 5: Deploy only after the user authorizes the hardware step**

Use:

```powershell
yoyopod target mode status
yoyopod target deploy --branch codex/stopwatch-flashlight --sha <full-commit-sha> --wait-for-ci
```

After deployment, verify Ready, Running, and Paused with the physical button, capture framebuffer and LVGL readback screenshots, confirm the top bar and bottom deck match the pre-change capture, and report the service/worker state. Physical-glass acceptance remains a human-eyes check.
