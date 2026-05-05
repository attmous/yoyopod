#[cfg(feature = "native-lvgl")]
use std::sync::{Mutex, MutexGuard, OnceLock};

use yoyopod_ui_host::hardware::mock::{MockButton, MockDisplay};
use yoyopod_ui_host::worker::run_worker;

#[cfg(feature = "native-lvgl")]
fn native_lvgl_test_guard() -> MutexGuard<'static, ()> {
    static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
    LOCK.get_or_init(|| Mutex::new(()))
        .lock()
        .expect("native LVGL test lock should not be poisoned")
}

#[test]
fn worker_emits_ready_and_health_for_mock_hardware() {
    let input = br#"{"schema_version":1,"kind":"command","type":"ui.show_test_scene","payload":{"counter":3}}
{"schema_version":1,"kind":"command","type":"ui.health","payload":{}}
{"schema_version":1,"kind":"command","type":"ui.shutdown","payload":{}}
"#;
    let mut output = Vec::new();
    let mut errors = Vec::new();
    let display = MockDisplay::new(240, 280);
    let button = MockButton::new();

    run_worker(input.as_slice(), &mut output, &mut errors, display, button)
        .expect("worker exits cleanly");

    let stdout = String::from_utf8(output).expect("utf8");
    assert!(stdout.contains("\"type\":\"ui.ready\""));
    assert!(stdout.contains("\"type\":\"ui.health\""));
    assert!(stdout.contains("\"frames\":1"));
}

#[test]
fn worker_renders_runtime_snapshot_and_reports_active_screen_from_screen_model() {
    let input = br#"{"schema_version":1,"kind":"command","type":"ui.runtime_snapshot","payload":{"renderer":"framebuffer","call":{"state":"incoming","peer_name":"Mama","peer_address":"+1 555-0100"}}}
{"schema_version":1,"kind":"command","type":"ui.health","payload":{}}
{"schema_version":1,"kind":"command","type":"ui.shutdown","payload":{}}
"#;
    let mut output = Vec::new();
    let mut errors = Vec::new();
    let display = MockDisplay::new(240, 280);
    let button = MockButton::new();

    run_worker(input.as_slice(), &mut output, &mut errors, display, button)
        .expect("worker exits cleanly");

    let stdout = String::from_utf8(output).expect("utf8");
    assert!(stdout.contains("\"type\":\"ui.screen_changed\""));
    assert!(stdout.contains("\"screen\":\"incoming_call\""));
    assert!(stdout.contains("\"frames\":1"));
    assert!(stdout.contains("\"active_screen\":\"incoming_call\""));
    assert!(stdout.contains("\"last_ui_renderer\":\"framebuffer\""));
    assert!(!stdout.contains("\"last_hub_renderer\""));
}

#[test]
fn worker_applies_semantic_input_inside_rust_state_machine() {
    let input =
        br#"{"schema_version":1,"kind":"command","type":"ui.runtime_snapshot","payload":{"renderer":"framebuffer"}}
{"schema_version":1,"kind":"command","type":"ui.input_action","payload":{"renderer":"framebuffer","action":"select"}}
{"schema_version":1,"kind":"command","type":"ui.health","payload":{}}
{"schema_version":1,"kind":"command","type":"ui.shutdown","payload":{}}
"#;
    let mut output = Vec::new();
    let mut errors = Vec::new();
    let display = MockDisplay::new(240, 280);
    let button = MockButton::new();

    run_worker(input.as_slice(), &mut output, &mut errors, display, button)
        .expect("worker exits cleanly");

    let stdout = String::from_utf8(output).expect("utf8");
    assert!(stdout.contains("\"screen\":\"listen\""));
    assert!(stdout.contains("\"active_screen\":\"listen\""));
}

#[test]
fn worker_emits_runtime_intent_for_call_action() {
    let input = br#"{"schema_version":1,"kind":"command","type":"ui.runtime_snapshot","payload":{"renderer":"framebuffer","call":{"state":"incoming","peer_name":"Mama"}}}
{"schema_version":1,"kind":"command","type":"ui.input_action","payload":{"renderer":"framebuffer","action":"select"}}
{"schema_version":1,"kind":"command","type":"ui.shutdown","payload":{}}
"#;
    let mut output = Vec::new();
    let mut errors = Vec::new();
    let display = MockDisplay::new(240, 280);
    let button = MockButton::new();

    run_worker(input.as_slice(), &mut output, &mut errors, display, button)
        .expect("worker exits cleanly");

    let stdout = String::from_utf8(output).expect("utf8");
    assert!(stdout.contains("\"type\":\"ui.intent\""));
    assert!(stdout.contains("\"domain\":\"call\""));
    assert!(stdout.contains("\"action\":\"answer\""));
}

#[cfg(not(feature = "native-lvgl"))]
#[test]
fn worker_explicit_lvgl_mode_emits_error_and_falls_back_without_exiting() {
    let input = br#"{"schema_version":1,"kind":"command","type":"ui.runtime_snapshot","payload":{"renderer":"lvgl","music":{"title":"Little Song","artist":"YoYo"}}}
{"schema_version":1,"kind":"command","type":"ui.health","payload":{}}
{"schema_version":1,"kind":"command","type":"ui.shutdown","payload":{}}
"#;
    let mut output = Vec::new();
    let mut errors = Vec::new();
    let display = MockDisplay::new(240, 280);
    let button = MockButton::new();

    run_worker(input.as_slice(), &mut output, &mut errors, display, button)
        .expect("worker exits cleanly");

    let stdout = String::from_utf8(output).expect("utf8");
    assert!(stdout.contains("\"type\":\"ui.error\""));
    assert!(stdout.contains("\"code\":\"lvgl_unavailable\""));
    assert!(stdout.contains("\"type\":\"ui.health\""));
    assert!(stdout.contains("\"last_ui_renderer\":\"framebuffer\""));
}

#[cfg(not(feature = "native-lvgl"))]
#[test]
fn worker_auto_mode_silently_falls_back_to_framebuffer() {
    let input = br#"{"schema_version":1,"kind":"command","type":"ui.runtime_snapshot","payload":{"music":{"title":"Little Song","artist":"YoYo"}}}
{"schema_version":1,"kind":"command","type":"ui.health","payload":{}}
{"schema_version":1,"kind":"command","type":"ui.shutdown","payload":{}}
"#;
    let mut output = Vec::new();
    let mut errors = Vec::new();
    let display = MockDisplay::new(240, 280);
    let button = MockButton::new();

    run_worker(input.as_slice(), &mut output, &mut errors, display, button)
        .expect("worker exits cleanly");

    let stdout = String::from_utf8(output).expect("utf8");
    assert!(!stdout.contains("\"type\":\"ui.error\""));
    assert!(stdout.contains("\"type\":\"ui.health\""));
    assert!(stdout.contains("\"last_ui_renderer\":\"framebuffer\""));
}

#[cfg(feature = "native-lvgl")]
#[test]
fn worker_explicit_lvgl_mode_uses_native_renderer_when_available() {
    let _guard = native_lvgl_test_guard();
    let input = br#"{"schema_version":1,"kind":"command","type":"ui.runtime_snapshot","payload":{"renderer":"lvgl","music":{"title":"Little Song","artist":"YoYo"}}}
{"schema_version":1,"kind":"command","type":"ui.health","payload":{}}
{"schema_version":1,"kind":"command","type":"ui.shutdown","payload":{}}
"#;
    let mut output = Vec::new();
    let mut errors = Vec::new();
    let display = MockDisplay::new(240, 280);
    let button = MockButton::new();

    run_worker(input.as_slice(), &mut output, &mut errors, display, button)
        .expect("worker exits cleanly");

    let stdout = String::from_utf8(output).expect("utf8");
    assert!(!stdout.contains("\"type\":\"ui.error\""));
    assert!(stdout.contains("\"type\":\"ui.health\""));
    assert!(stdout.contains("\"last_ui_renderer\":\"lvgl\""));
}

#[cfg(feature = "native-lvgl")]
#[test]
fn worker_auto_mode_prefers_native_renderer_when_available() {
    let _guard = native_lvgl_test_guard();
    let input = br#"{"schema_version":1,"kind":"command","type":"ui.runtime_snapshot","payload":{"music":{"title":"Little Song","artist":"YoYo"}}}
{"schema_version":1,"kind":"command","type":"ui.health","payload":{}}
{"schema_version":1,"kind":"command","type":"ui.shutdown","payload":{}}
"#;
    let mut output = Vec::new();
    let mut errors = Vec::new();
    let display = MockDisplay::new(240, 280);
    let button = MockButton::new();

    run_worker(input.as_slice(), &mut output, &mut errors, display, button)
        .expect("worker exits cleanly");

    let stdout = String::from_utf8(output).expect("utf8");
    assert!(!stdout.contains("\"type\":\"ui.error\""));
    assert!(stdout.contains("\"type\":\"ui.health\""));
    assert!(stdout.contains("\"last_ui_renderer\":\"lvgl\""));
}
