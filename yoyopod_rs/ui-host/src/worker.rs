use std::io::{BufRead, BufReader, Read, Write};

use anyhow::{bail, Result};
use serde_json::json;

use crate::framebuffer::Framebuffer;
use crate::hardware::{ButtonDevice, DisplayDevice};
use crate::hub::{HubCommand, HubRenderer};
use crate::input::{ButtonTiming, InputAction, OneButtonMachine};
use crate::lvgl_bridge::render_hub_with_lvgl;
use crate::protocol::{Envelope, EnvelopeKind};
use crate::render::{
    render_hub_fallback, render_test_scene, FramebufferRenderer, LvglRenderer, RendererMode,
};
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
    let mut lvgl_renderer = match LvglRenderer::open(None) {
        Ok(renderer) => Some(renderer),
        Err(err) => {
            writeln!(
                errors,
                "LVGL runtime renderer unavailable; using framebuffer diagnostic renderer: {err}"
            )?;
            None
        }
    };

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
                            &mut lvgl_renderer,
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
                            &mut lvgl_renderer,
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
                            &mut lvgl_renderer,
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
    renderer: RendererMode,
    last_ui_renderer: &mut String,
    lvgl_renderer: &mut Option<LvglRenderer>,
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
        RendererMode::Auto => {
            if let Some(renderer) = lvgl_renderer.as_mut() {
                renderer.render_view(framebuffer, &view, ui_runtime.snapshot())?;
                *last_ui_renderer = RendererMode::Lvgl.as_str().to_string();
            } else {
                writeln!(
                    errors,
                    "LVGL runtime renderer unavailable; using framebuffer diagnostic renderer"
                )?;
                FramebufferRenderer::render_view(framebuffer, &view, ui_runtime.snapshot());
                *last_ui_renderer = RendererMode::Framebuffer.as_str().to_string();
            }
        }
        RendererMode::Framebuffer => {
            FramebufferRenderer::render_view(framebuffer, &view, ui_runtime.snapshot());
            *last_ui_renderer = RendererMode::Framebuffer.as_str().to_string();
        }
        RendererMode::Lvgl => {
            let Some(renderer) = lvgl_renderer.as_mut() else {
                emit(
                    output,
                    Envelope::error("lvgl_unavailable", "LVGL runtime renderer unavailable"),
                )?;
                bail!("LVGL runtime renderer unavailable");
            };
            renderer.render_view(framebuffer, &view, ui_runtime.snapshot())?;
            *last_ui_renderer = RendererMode::Lvgl.as_str().to_string();
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

fn renderer_from_payload(payload: &serde_json::Value) -> Result<RendererMode> {
    match payload
        .get("renderer")
        .and_then(|value| value.as_str())
        .unwrap_or("auto")
    {
        "auto" => Ok(RendererMode::Auto),
        "lvgl" => Ok(RendererMode::Lvgl),
        "framebuffer" => Ok(RendererMode::Framebuffer),
        value => bail!("unknown UI renderer {value:?}"),
    }
}
