use std::io::{BufRead, BufReader, Read, Write};

use anyhow::{bail, Result};
use serde_json::json;

use crate::framebuffer::Framebuffer;
use crate::hardware::{ButtonDevice, DisplayDevice};
use crate::hub::{HubCommand, HubRenderer};
use crate::input::{ButtonTiming, InputAction, OneButtonMachine};
use crate::lvgl_bridge::{render_hub_with_lvgl, render_view_with_lvgl};
use crate::protocol::{Envelope, EnvelopeKind};
use crate::render::{render_hub_fallback, render_test_scene, render_ui_view_fallback};
use crate::runtime::{RuntimeSnapshot, UiIntent, UiRuntime, UiScreen};

pub fn run_worker<R, W, E, D, B>(
    input: R,
    output: &mut W,
    errors: &mut E,
    mut display: D,
    mut button: B,
) -> Result<()>
where
    R: Read,
    W: Write,
    E: Write,
    D: DisplayDevice,
    B: ButtonDevice,
{
    let mut framebuffer = Framebuffer::new(display.width(), display.height());
    let mut frames = 0usize;
    let mut input_events = 0usize;
    let mut last_hub_renderer = String::new();
    let mut last_ui_renderer = String::new();
    let mut button_machine = OneButtonMachine::new(ButtonTiming::default());
    let mut ui_runtime = UiRuntime::default();
    let mut last_active_screen: Option<UiScreen> = None;

    emit(
        output,
        Envelope::event(
            "ui.ready",
            json!({
                "display": {"width": display.width(), "height": display.height()},
            }),
        ),
    )?;

    let reader = BufReader::new(input);
    for line in reader.lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }

        match Envelope::decode(line.as_bytes()) {
            Ok(envelope) => {
                if envelope.kind != EnvelopeKind::Command {
                    emit(
                        output,
                        Envelope::error("invalid_kind", "worker accepts commands only"),
                    )?;
                    continue;
                }

                match envelope.message_type.as_str() {
                    "ui.show_test_scene" => {
                        let counter = envelope
                            .payload
                            .get("counter")
                            .and_then(|value| value.as_u64())
                            .unwrap_or(frames as u64 + 1);
                        render_test_scene(&mut framebuffer, counter);
                        display.flush_full_frame(&framebuffer)?;
                        frames += 1;
                    }
                    "ui.show_hub" => {
                        let command = HubCommand::from_payload(&envelope.payload)?;
                        match command.renderer {
                            HubRenderer::Auto => {
                                match render_hub_with_lvgl(
                                    &mut framebuffer,
                                    &command.snapshot,
                                    None,
                                ) {
                                    Ok(()) => {
                                        last_hub_renderer = HubRenderer::Lvgl.as_str().to_string();
                                    }
                                    Err(err) => {
                                        writeln!(
                                            errors,
                                            "LVGL Hub renderer unavailable; falling back: {err}"
                                        )?;
                                        render_hub_fallback(&mut framebuffer, &command.snapshot);
                                        last_hub_renderer =
                                            HubRenderer::Framebuffer.as_str().to_string();
                                    }
                                }
                            }
                            HubRenderer::Framebuffer => {
                                render_hub_fallback(&mut framebuffer, &command.snapshot);
                                last_hub_renderer = HubRenderer::Framebuffer.as_str().to_string();
                            }
                            HubRenderer::Lvgl => {
                                render_hub_with_lvgl(&mut framebuffer, &command.snapshot, None)?;
                                last_hub_renderer = HubRenderer::Lvgl.as_str().to_string();
                            }
                        }
                        display.flush_full_frame(&framebuffer)?;
                        frames += 1;
                    }
                    "ui.set_backlight" => {
                        let brightness = envelope
                            .payload
                            .get("brightness")
                            .and_then(|value| value.as_f64())
                            .unwrap_or(0.8) as f32;
                        display.set_backlight(brightness.clamp(0.0, 1.0))?;
                    }
                    "ui.runtime_snapshot" => {
                        let renderer = renderer_from_payload(&envelope.payload)?;
                        let snapshot = RuntimeSnapshot::from_payload(&envelope.payload)?;
                        ui_runtime.apply_snapshot(snapshot);
                        if render_runtime_if_dirty(
                            output,
                            errors,
                            &mut display,
                            &mut framebuffer,
                            &mut ui_runtime,
                            &mut last_active_screen,
                            renderer,
                            &mut last_ui_renderer,
                        )? {
                            frames += 1;
                        }
                    }
                    "ui.input_action" => {
                        let renderer = renderer_from_payload(&envelope.payload)?;
                        let action = parse_input_action(&envelope.payload)?;
                        ui_runtime.handle_input(action);
                        emit_intents(output, ui_runtime.take_intents())?;
                        if render_runtime_if_dirty(
                            output,
                            errors,
                            &mut display,
                            &mut framebuffer,
                            &mut ui_runtime,
                            &mut last_active_screen,
                            renderer,
                            &mut last_ui_renderer,
                        )? {
                            frames += 1;
                        }
                    }
                    "ui.tick" => {
                        let renderer = renderer_from_payload(&envelope.payload)?;
                        let pressed = button.pressed()?;
                        let now_ms = crate::protocol::monotonic_millis();
                        for event in button_machine.observe(pressed, now_ms) {
                            input_events += 1;
                            emit(
                                output,
                                Envelope::event(
                                    "ui.input",
                                    json!({
                                        "action": event.action.as_str(),
                                        "method": event.method,
                                        "timestamp_ms": event.timestamp_ms,
                                        "duration_ms": event.duration_ms,
                                    }),
                                ),
                            )?;
                            ui_runtime.handle_input(event.action);
                        }
                        emit_intents(output, ui_runtime.take_intents())?;
                        if render_runtime_if_dirty(
                            output,
                            errors,
                            &mut display,
                            &mut framebuffer,
                            &mut ui_runtime,
                            &mut last_active_screen,
                            renderer,
                            &mut last_ui_renderer,
                        )? {
                            frames += 1;
                        }
                    }
                    "ui.poll_input" => {
                        let pressed = button.pressed()?;
                        let now_ms = crate::protocol::monotonic_millis();
                        for event in button_machine.observe(pressed, now_ms) {
                            input_events += 1;
                            emit(
                                output,
                                Envelope::event(
                                    "ui.input",
                                    json!({
                                        "action": event.action.as_str(),
                                        "method": event.method,
                                        "timestamp_ms": event.timestamp_ms,
                                        "duration_ms": event.duration_ms,
                                    }),
                                ),
                            )?;
                        }
                    }
                    "ui.health" => {
                        emit(
                            output,
                            Envelope::event(
                                "ui.health",
                                json!({
                                    "frames": frames,
                                    "button_events": input_events,
                                    "last_hub_renderer": last_hub_renderer,
                                    "last_ui_renderer": last_ui_renderer,
                                    "active_screen": ui_runtime.active_screen().as_str(),
                                }),
                            ),
                        )?;
                    }
                    "ui.shutdown" | "worker.stop" => break,
                    other => {
                        writeln!(errors, "unknown UI worker command: {other}")?;
                        emit(output, Envelope::error("unknown_command", other))?;
                    }
                }
            }
            Err(err) => {
                writeln!(errors, "protocol decode error: {err}")?;
                emit(output, Envelope::error("decode_error", err.to_string()))?;
            }
        }
    }

    Ok(())
}

fn emit<W: Write>(output: &mut W, envelope: Envelope) -> Result<()> {
    output.write_all(&envelope.encode()?)?;
    output.flush()?;
    Ok(())
}

fn emit_intents<W: Write>(output: &mut W, intents: Vec<UiIntent>) -> Result<()> {
    for intent in intents {
        emit(
            output,
            Envelope::event(
                "ui.intent",
                json!({
                    "domain": intent.domain,
                    "action": intent.action,
                    "payload": intent.payload,
                }),
            ),
        )?;
    }
    Ok(())
}

fn render_runtime_if_dirty<W, D>(
    output: &mut W,
    errors: &mut impl Write,
    display: &mut D,
    framebuffer: &mut Framebuffer,
    ui_runtime: &mut UiRuntime,
    last_active_screen: &mut Option<UiScreen>,
    renderer: HubRenderer,
    last_ui_renderer: &mut String,
) -> Result<bool>
where
    W: Write,
    D: DisplayDevice,
{
    if !ui_runtime.is_dirty() {
        return Ok(false);
    }

    let view = ui_runtime.active_view();
    match renderer {
        HubRenderer::Auto => {
            match render_view_with_lvgl(framebuffer, &view, ui_runtime.snapshot(), None) {
                Ok(()) => {
                    *last_ui_renderer = HubRenderer::Lvgl.as_str().to_string();
                }
                Err(err) => {
                    writeln!(
                        errors,
                        "LVGL runtime renderer unavailable; falling back: {err}"
                    )?;
                    render_ui_view_fallback(framebuffer, &view, ui_runtime.snapshot());
                    *last_ui_renderer = HubRenderer::Framebuffer.as_str().to_string();
                }
            }
        }
        HubRenderer::Framebuffer => {
            render_ui_view_fallback(framebuffer, &view, ui_runtime.snapshot());
            *last_ui_renderer = HubRenderer::Framebuffer.as_str().to_string();
        }
        HubRenderer::Lvgl => {
            render_view_with_lvgl(framebuffer, &view, ui_runtime.snapshot(), None)?;
            *last_ui_renderer = HubRenderer::Lvgl.as_str().to_string();
        }
    }
    display.flush_full_frame(framebuffer)?;
    if last_active_screen
        .map(|screen| screen != view.screen)
        .unwrap_or(true)
    {
        emit(
            output,
            Envelope::event(
                "ui.screen_changed",
                json!({
                    "screen": view.screen.as_str(),
                    "title": view.title,
                }),
            ),
        )?;
        *last_active_screen = Some(view.screen);
    }
    ui_runtime.mark_clean();
    Ok(true)
}

fn parse_input_action(payload: &serde_json::Value) -> Result<InputAction> {
    let action = payload
        .get("action")
        .and_then(|value| value.as_str())
        .unwrap_or("");
    match action {
        "advance" => Ok(InputAction::Advance),
        "select" => Ok(InputAction::Select),
        "back" => Ok(InputAction::Back),
        "ptt_press" => Ok(InputAction::PttPress),
        "ptt_release" => Ok(InputAction::PttRelease),
        value => bail!("unknown UI input action {value:?}"),
    }
}

fn renderer_from_payload(payload: &serde_json::Value) -> Result<HubRenderer> {
    match payload
        .get("renderer")
        .and_then(|value| value.as_str())
        .unwrap_or("auto")
    {
        "auto" => Ok(HubRenderer::Auto),
        "lvgl" => Ok(HubRenderer::Lvgl),
        "framebuffer" => Ok(HubRenderer::Framebuffer),
        value => bail!("unknown UI renderer {value:?}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::hardware::mock::{MockButton, MockDisplay};

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
        let input =
            br#"{"kind":"command","type":"ui.show_hub","payload":{"renderer":"framebuffer"}}
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
}
