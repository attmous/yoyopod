use yoyopod_ui_host::hardware::mock::{MockButton, MockDisplay};
use yoyopod_ui_host::worker::run_worker;

#[test]
fn worker_emits_ready_and_health_for_mock_hardware() {
    let input = br#"{"kind":"command","type":"ui.show_test_scene","payload":{"counter":3}}
{"kind":"command","type":"ui.health","payload":{}}
{"kind":"command","type":"ui.shutdown","payload":{}}
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
fn worker_renders_static_hub_with_framebuffer_renderer() {
    let input = br#"{"kind":"command","type":"ui.show_hub","payload":{"renderer":"framebuffer"}}
{"kind":"command","type":"ui.health","payload":{}}
{"kind":"command","type":"ui.shutdown","payload":{}}
"#;
    let mut output = Vec::new();
    let mut errors = Vec::new();
    let display = MockDisplay::new(240, 280);
    let button = MockButton::new();

    run_worker(input.as_slice(), &mut output, &mut errors, display, button)
        .expect("worker exits cleanly");

    let stdout = String::from_utf8(output).expect("utf8");
    assert!(stdout.contains("\"frames\":1"));
    assert!(stdout.contains("\"last_hub_renderer\":\"framebuffer\""));
}

#[test]
fn worker_renders_runtime_snapshot_and_reports_active_screen() {
    let input = br#"{"kind":"command","type":"ui.runtime_snapshot","payload":{"music":{"title":"Little Song","artist":"YoYo"}}}
{"kind":"command","type":"ui.health","payload":{}}
{"kind":"command","type":"ui.shutdown","payload":{}}
"#;
    let mut output = Vec::new();
    let mut errors = Vec::new();
    let display = MockDisplay::new(240, 280);
    let button = MockButton::new();

    run_worker(input.as_slice(), &mut output, &mut errors, display, button)
        .expect("worker exits cleanly");

    let stdout = String::from_utf8(output).expect("utf8");
    assert!(stdout.contains("\"type\":\"ui.screen_changed\""));
    assert!(stdout.contains("\"screen\":\"hub\""));
    assert!(stdout.contains("\"frames\":1"));
    assert!(stdout.contains("\"active_screen\":\"hub\""));
}

#[test]
fn worker_applies_semantic_input_inside_rust_state_machine() {
    let input = br#"{"kind":"command","type":"ui.runtime_snapshot","payload":{}}
{"kind":"command","type":"ui.input_action","payload":{"action":"select"}}
{"kind":"command","type":"ui.health","payload":{}}
{"kind":"command","type":"ui.shutdown","payload":{}}
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
    let input = br#"{"kind":"command","type":"ui.runtime_snapshot","payload":{"call":{"state":"incoming","peer_name":"Mama"}}}
{"kind":"command","type":"ui.input_action","payload":{"action":"select"}}
{"kind":"command","type":"ui.shutdown","payload":{}}
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
