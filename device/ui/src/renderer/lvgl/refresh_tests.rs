use std::process::Command;
use std::sync::atomic::{AtomicU32, Ordering};
use std::time::{Duration, Instant};

use super::*;
use crate::application::UiRuntime;
use crate::engine::Engine;
use crate::renderer::widgets::LvglFacade;
use crate::renderer::{LvglRenderer, Renderer};
use yoyopod_protocol::ui::{InputAction, RuntimeSnapshot, RuntimeSnapshotPatch, UiScreen};

static NATIVE_TEST_TICK: AtomicU32 = AtomicU32::new(0);

// Pinned LVGL9.5 src/tick/lv_tick.h; a test-owned clock prevents host timing
// from accidentally making the periodic refresh due between permission frames.
unsafe extern "C" {
    fn lv_tick_set_cb(callback: Option<extern "C" fn() -> u32>);
}

extern "C" fn native_test_tick() -> u32 {
    NATIVE_TEST_TICK.load(Ordering::Relaxed)
}

#[test]
fn completed_native_frames_have_current_shadow_pixels_within_refresh_period() {
    const CHILD_MARKER: &str = "YOYOPOD_NATIVE_REFRESH_TEST_CHILD";
    const COMPLETED: &str = "NATIVE_REFRESH_CASE_COMPLETED";
    if std::env::var(CHILD_MARKER).as_deref() == Ok("1") {
        native_frame_completion_cases();
        println!("{COMPLETED}");
        return;
    }
    // Isolate LVGL process-global init/deinit from existing worker tests. The
    // exact selection and completion marker prove the child ran this case,
    // rather than silently succeeding with zero selected tests.
    let output = Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            concat!(
                module_path!(),
                "::completed_native_frames_have_current_shadow_pixels_within_refresh_period"
            ),
            "--nocapture",
        ])
        .env(CHILD_MARKER, "1")
        .output()
        .expect("spawn isolated native refresh test");
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "native child failed:\n{stdout}\n{stderr}"
    );
    assert!(
        stdout.contains(COMPLETED),
        "native child did not complete the case:\n{stdout}\n{stderr}"
    );
}

// All native cases run on the child test's owning thread, one initialized
// facade at a time. No LVGL calls occur in the parent test process.
fn native_frame_completion_cases() {
    let mut facade = NativeLvglFacade::open(None).unwrap();
    let mut framebuffer = Framebuffer::new(240, 280);
    facade.ensure_display_registered(&framebuffer).unwrap();
    let root = facade.create_root().unwrap();
    let panel = facade.create_container(root, "button").unwrap();
    let object = facade.widget_obj(panel).unwrap();

    unsafe {
        ffi::lv_obj_set_style_bg_opa(object.as_ptr(), 255, 0);
        ffi::lv_obj_set_style_bg_color(object.as_ptr(), ffi::lv_color_hex(0xff0000), 0);
        // Make the initial periodic refresh due without a wall-clock sleep.
        ffi::lv_tick_inc(33);
    }
    render_with_one_ms_tick(&mut facade, &mut framebuffer);
    assert_eq!(framebuffer.pixels()[160 * 240 + 120], 0xf800);

    for (color, expected) in [(0x00ff00, 0x07e0), (0x0000ff, 0x001f), (0xff0000, 0xf800)] {
        unsafe {
            ffi::lv_obj_set_style_bg_color(object.as_ptr(), ffi::lv_color_hex(color), 0);
        }
        render_with_one_ms_tick(&mut facade, &mut framebuffer);
        assert_eq!(
            framebuffer.pixels()[160 * 240 + 120],
            expected,
            "completed frame must contain the changed color before the periodic refresh is due"
        );
    }
    assert!(facade.flush_target.framebuffer.is_null());
    framebuffer.clear(0xaaaa);
    unsafe {
        // A later LVGL callback must no longer borrow the returned framebuffer.
        ffi::lv_obj_invalidate(object.as_ptr());
        ffi::lv_tick_inc(33);
        let _ = ffi::lv_timer_handler();
    }
    assert!(framebuffer.pixels().iter().all(|pixel| *pixel == 0xaaaa));
    drop(facade);
    retained_permission_frames();
}

fn render_with_one_ms_tick(facade: &mut NativeLvglFacade, framebuffer: &mut Framebuffer) {
    // tick_lvgl uses max(elapsed, 1). A future origin gives a deterministic
    // one-ms tick even on a preempted/slow test host, without changing LVGL's
    // refresh period or calling a separate redraw/snapshot API.
    facade.last_tick = Instant::now() + Duration::from_secs(3_600);
    facade.render_frame(framebuffer).unwrap();
}

fn retained_permission_frames() {
    let mut renderer = LvglRenderer::open(None).unwrap();
    let mut framebuffer = Framebuffer::new(240, 280);
    NATIVE_TEST_TICK.store(0, Ordering::Relaxed);
    unsafe {
        lv_tick_set_cb(Some(native_test_tick));
    }
    renderer.initialize_display(&framebuffer).unwrap();
    let mut runtime = UiRuntime::default();
    let mut snapshot = RuntimeSnapshot {
        app_state: UiScreen::VoiceNote,
        ..Default::default()
    };
    snapshot.voice.interrupted_draft_path = Some("owned.wav".into());
    snapshot.voice.interrupted_draft_id = "draft-a".into();
    snapshot.voice.interrupted_draft_phase = "review".into();
    snapshot.voice.interrupted_draft_send_allowed = true;
    runtime.apply_snapshot(snapshot);
    let mut engine = Engine::default();
    NATIVE_TEST_TICK.store(33, Ordering::Relaxed);
    draw_runtime(
        &mut runtime,
        &mut engine,
        &mut renderer,
        &mut framebuffer,
        1_000,
    );
    NATIVE_TEST_TICK.store(66, Ordering::Relaxed);
    runtime.mark_animation_frame();
    draw_runtime(
        &mut runtime,
        &mut engine,
        &mut renderer,
        &mut framebuffer,
        1_300,
    );
    // Real input goes through Review, Discard and wraps to Send. Freeze the
    // native clock during these and all immediate permission-only frames.
    for _ in 0..3 {
        runtime.handle_input(InputAction::Advance, 1_300);
        draw_runtime(
            &mut runtime,
            &mut engine,
            &mut renderer,
            &mut framebuffer,
            1_300,
        );
    }
    assert_eq!(runtime.focus_index, 0);
    let before = framebuffer.as_be_bytes_region(10, 26, 130, 14);
    let mut revoked = runtime.snapshot.clone();
    revoked.voice.interrupted_draft_send_allowed = false;
    runtime.apply_snapshot(revoked);
    assert_eq!(runtime.active_title(), "Send unavailable");
    draw_runtime(
        &mut runtime,
        &mut engine,
        &mut renderer,
        &mut framebuffer,
        1_300,
    );
    assert_current_caption(
        &mut runtime,
        &mut engine,
        &mut renderer,
        &mut framebuffer,
        &before,
        130,
    );
    runtime.handle_input(InputAction::Select, 1_300);
    assert!(runtime.take_intents().is_empty());

    let before = framebuffer.as_be_bytes_region(10, 26, 130, 14);
    let mut voice = runtime.snapshot.voice.clone();
    voice.interrupted_draft_send_allowed = true;
    runtime.apply_patch(RuntimeSnapshotPatch::Voice(voice.clone()));
    draw_runtime(
        &mut runtime,
        &mut engine,
        &mut renderer,
        &mut framebuffer,
        1_300,
    );
    assert_current_caption(
        &mut runtime,
        &mut engine,
        &mut renderer,
        &mut framebuffer,
        &before,
        130,
    );

    voice.interrupted_draft_phase = "unknown".into();
    runtime.apply_patch(RuntimeSnapshotPatch::Voice(voice.clone()));
    draw_runtime(
        &mut runtime,
        &mut engine,
        &mut renderer,
        &mut framebuffer,
        1_300,
    );
    let before = framebuffer.as_be_bytes_region(10, 26, 220, 14);
    voice.interrupted_draft_send_allowed = false;
    runtime.apply_patch(RuntimeSnapshotPatch::Voice(voice));
    assert_eq!(
        runtime.active_title(),
        "Delivery unknown · Send unavailable"
    );
    draw_runtime(
        &mut runtime,
        &mut engine,
        &mut renderer,
        &mut framebuffer,
        1_300,
    );
    assert_current_caption(
        &mut runtime,
        &mut engine,
        &mut renderer,
        &mut framebuffer,
        &before,
        220,
    );
}

fn draw_runtime(
    runtime: &mut UiRuntime,
    engine: &mut Engine,
    renderer: &mut LvglRenderer,
    framebuffer: &mut Framebuffer,
    now_ms: u64,
) {
    let request = runtime
        .frame_request(now_ms)
        .expect("snapshot/input dirtiness");
    renderer
        .apply(engine.render(&request.scene_graph, now_ms))
        .unwrap();
    renderer
        .flush(framebuffer, crate::RenderMode::FullFrame)
        .unwrap();
    runtime.mark_clean();
}

fn assert_current_caption(
    runtime: &mut UiRuntime,
    engine: &mut Engine,
    renderer: &mut LvglRenderer,
    framebuffer: &mut Framebuffer,
    before: &[u8],
    width: usize,
) {
    let immediate = framebuffer.as_be_bytes_region(10, 26, width, 14);
    assert_ne!(
        immediate, before,
        "permission-only completed frame changes caption pixels"
    );
    // A normal due periodic redraw is an independent native pixel reference.
    // No snapshot API or sleeps can hide a stale returned framebuffer.
    NATIVE_TEST_TICK.fetch_add(33, Ordering::Relaxed);
    runtime.mark_animation_frame();
    draw_runtime(runtime, engine, renderer, framebuffer, 1_300);
    assert_eq!(immediate, framebuffer.as_be_bytes_region(10, 26, width, 14));
}
