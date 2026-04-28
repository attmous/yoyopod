# Rust Static Hub UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a static Hub screen command to the Rust Whisplay sidecar using the current Python LVGL Hub sync field names.

**Architecture:** Add a Rust `HubSnapshot` model and `ui.show_hub` command, render through a native LVGL shim bridge when requested, and keep a deterministic framebuffer fallback for host tests. Add a Python payload helper plus CLI options so hardware validation can force the LVGL renderer.

**Tech Stack:** Rust 2021, Cargo, `serde_json`, optional dynamic native LVGL shim loading, Python 3.12, Typer, pytest.

---

## File Structure

- Create: `workers/ui/rust/src/hub.rs` - Hub view-model parser and renderer option parsing.
- Create: `workers/ui/rust/src/lvgl_bridge.rs` - optional dynamic bridge to the existing native LVGL shim.
- Modify: `workers/ui/rust/src/framebuffer.rs` - copy RGB565 partial regions into the full framebuffer.
- Modify: `workers/ui/rust/src/render.rs` - add deterministic static Hub fallback renderer.
- Modify: `workers/ui/rust/src/worker.rs` - handle `ui.show_hub` and report `last_hub_renderer` in health.
- Modify: `workers/ui/rust/src/main.rs` - register new modules.
- Modify: `workers/ui/rust/Cargo.toml` - add dynamic loading dependency.
- Create: `yoyopod/ui/rust_sidecar/hub.py` - Python static Hub payload helper.
- Modify: `yoyopod_cli/pi/rust_ui_poc.py` - add `--screen` and `--hub-renderer` options.
- Modify: `tests/ui/test_rust_sidecar_protocol.py` - verify the Python Hub payload contract.
- Modify: `tests/cli/test_pi_rust_ui_poc.py` - verify CLI sends `ui.show_hub`.
- Modify: `tests/core/test_rust_ui_worker_contract.py` - verify mock worker accepts `ui.show_hub`.

---

### Task 1: Add Hub Contract Tests

- [ ] Add Rust tests in `workers/ui/rust/src/hub.rs` for default static Hub payloads and explicit LVGL field parsing.
- [ ] Run `cargo test hub::tests` and confirm the tests fail because `hub.rs` is not registered yet.
- [ ] Add Python tests for the static Hub payload helper and CLI `--screen hub` command.
- [ ] Run the focused Python tests and confirm they fail because the helper and CLI options are missing.

### Task 2: Add Hub View-Model And Fallback Rendering

- [ ] Implement `HubSnapshot`, `HubRenderer`, and `HubCommand` in `workers/ui/rust/src/hub.rs`.
- [ ] Add `render_hub_fallback()` in `workers/ui/rust/src/render.rs`.
- [ ] Add `Framebuffer::paste_be_bytes_region()` for LVGL partial flush support.
- [ ] Register the `hub` module in `workers/ui/rust/src/main.rs`.
- [ ] Run `cargo test hub::tests render::tests framebuffer::tests`.

### Task 3: Add Optional LVGL Bridge

- [ ] Add `libloading` to `workers/ui/rust/Cargo.toml`.
- [ ] Implement `workers/ui/rust/src/lvgl_bridge.rs` with dynamic loading for `yoyopod_lvgl_init`, `yoyopod_lvgl_register_display`, `yoyopod_lvgl_hub_build`, `yoyopod_lvgl_hub_sync`, `yoyopod_lvgl_force_refresh`, `yoyopod_lvgl_timer_handler`, `yoyopod_lvgl_shutdown`, and `yoyopod_lvgl_last_error`.
- [ ] Convert LVGL flush callbacks into `Framebuffer::paste_be_bytes_region()` calls.
- [ ] Make forced `renderer="lvgl"` fail when the shim cannot be found.
- [ ] Run `cargo test lvgl_bridge::tests` for path-resolution and framebuffer-copy behavior.

### Task 4: Wire Worker And CLI

- [ ] Handle `ui.show_hub` in `workers/ui/rust/src/worker.rs`.
- [ ] Track `last_hub_renderer` and include it in `ui.health`.
- [ ] Add `RustHubSnapshot.static()` in `yoyopod/ui/rust_sidecar/hub.py`.
- [ ] Add `--screen test-scene|hub` and `--hub-renderer auto|lvgl|framebuffer` to `yoyopod pi rust-ui-poc`.
- [ ] Run focused Rust and Python tests for the worker contract and CLI.

### Task 5: Verify

- [ ] Run `cargo test --manifest-path workers/ui/rust/Cargo.toml`.
- [ ] Run `uv run python scripts/quality.py gate`.
- [ ] Run `uv run pytest -q`.
- [ ] If committing, run the same two repo gates immediately before `git commit`.
