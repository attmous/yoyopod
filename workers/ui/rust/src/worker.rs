use std::io::{BufRead, BufReader, Read, Write};

use anyhow::Result;
use serde_json::json;

use crate::framebuffer::Framebuffer;
use crate::hardware::{ButtonDevice, DisplayDevice};
use crate::hub::{HubCommand, HubRenderer};
use crate::input::{ButtonTiming, OneButtonMachine};
use crate::lvgl_bridge::render_hub_with_lvgl;
use crate::protocol::{Envelope, EnvelopeKind};
use crate::render::{render_hub_fallback, render_test_scene};

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
    let mut button_machine = OneButtonMachine::new(ButtonTiming::default());

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
}
