use std::io::{BufRead, BufReader, Read, Write};

use anyhow::{bail, Result};
use serde_json::json;

use crate::framebuffer::Framebuffer;
use crate::hardware::{ButtonDevice, DisplayDevice};
use crate::input::{ButtonTiming, InputAction, OneButtonMachine};
use crate::protocol::{error_envelope, event_envelope, Envelope, EnvelopeKind};
use crate::render::{render_test_scene, FramebufferRenderer, LvglRenderer, RendererMode};
use crate::runtime::{RuntimeSnapshot, UiIntent, UiRuntime, UiScreen};
use crate::screens::ScreenModel;

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
    let mut last_ui_renderer = String::new();
    let mut button_machine = OneButtonMachine::new(ButtonTiming::default());
    let mut ui_runtime = UiRuntime::default();
    let mut last_active_screen: Option<UiScreen> = None;
    let mut lvgl_renderer: Option<LvglRenderer> = None;

    emit(
        output,
        event_envelope(
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
                        error_envelope("invalid_kind", "worker accepts commands only"),
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
                        let button_events = if ui_runtime.wants_ptt_passthrough() {
                            button_machine.observe_ptt_passthrough(pressed, now_ms)
                        } else {
                            button_machine.observe(pressed, now_ms)
                        };
                        for event in button_events {
                            input_events += 1;
                            emit(
                                output,
                                event_envelope(
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
                        let button_events = if ui_runtime.wants_ptt_passthrough() {
                            button_machine.observe_ptt_passthrough(pressed, now_ms)
                        } else {
                            button_machine.observe(pressed, now_ms)
                        };
                        for event in button_events {
                            input_events += 1;
                            emit(
                                output,
                                event_envelope(
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
                        let active_screen = ui_runtime.active_screen_model().screen();
                        emit(
                            output,
                            event_envelope(
                                "ui.health",
                                json!({
                                    "frames": frames,
                                    "button_events": input_events,
                                    "last_ui_renderer": last_ui_renderer,
                                    "active_screen": active_screen.as_str(),
                                }),
                            ),
                        )?;
                    }
                    "ui.shutdown" | "worker.stop" => break,
                    other => {
                        writeln!(errors, "unknown UI worker command: {other}")?;
                        emit(output, error_envelope("unknown_command", other))?;
                    }
                }
            }
            Err(err) => {
                writeln!(errors, "protocol decode error: {err}")?;
                emit(output, error_envelope("decode_error", err.to_string()))?;
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
            event_envelope(
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

trait ActiveLvglRenderer {
    fn render_screen_model(
        &mut self,
        framebuffer: &mut Framebuffer,
        screen_model: &ScreenModel,
    ) -> Result<()>;
}

impl ActiveLvglRenderer for LvglRenderer {
    fn render_screen_model(
        &mut self,
        framebuffer: &mut Framebuffer,
        screen_model: &ScreenModel,
    ) -> Result<()> {
        self.render_screen_model(framebuffer, screen_model)
    }
}

#[allow(clippy::too_many_arguments)]
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

    let screen_model = ui_runtime.active_screen_model();
    match renderer {
        RendererMode::Auto => {
            if lvgl_renderer.is_none() {
                if let Ok(renderer) = LvglRenderer::open(None) {
                    *lvgl_renderer = Some(renderer);
                } else {
                    return render_runtime_with_framebuffer(
                        output,
                        display,
                        framebuffer,
                        ui_runtime,
                        last_active_screen,
                        &screen_model,
                        last_ui_renderer,
                    );
                }
            }

            let Some(renderer) = lvgl_renderer.as_mut() else {
                return render_runtime_with_framebuffer(
                    output,
                    display,
                    framebuffer,
                    ui_runtime,
                    last_active_screen,
                    &screen_model,
                    last_ui_renderer,
                );
            };

            render_runtime_with_active_lvgl_or_fallback(
                output,
                errors,
                display,
                framebuffer,
                ui_runtime,
                last_active_screen,
                &screen_model,
                last_ui_renderer,
                renderer,
                false,
            )
        }
        RendererMode::Framebuffer => render_runtime_with_framebuffer(
            output,
            display,
            framebuffer,
            ui_runtime,
            last_active_screen,
            &screen_model,
            last_ui_renderer,
        ),
        RendererMode::Lvgl => {
            if lvgl_renderer.is_none() {
                match LvglRenderer::open(None) {
                    Ok(renderer) => *lvgl_renderer = Some(renderer),
                    Err(err) => {
                        emit_explicit_lvgl_unavailable(output, errors, &err)?;
                        return render_runtime_with_framebuffer(
                            output,
                            display,
                            framebuffer,
                            ui_runtime,
                            last_active_screen,
                            &screen_model,
                            last_ui_renderer,
                        );
                    }
                }
            }
            let Some(renderer) = lvgl_renderer.as_mut() else {
                emit_explicit_lvgl_unavailable(output, errors, &"renderer failed to initialize")?;
                return render_runtime_with_framebuffer(
                    output,
                    display,
                    framebuffer,
                    ui_runtime,
                    last_active_screen,
                    &screen_model,
                    last_ui_renderer,
                );
            };
            render_runtime_with_active_lvgl_or_fallback(
                output,
                errors,
                display,
                framebuffer,
                ui_runtime,
                last_active_screen,
                &screen_model,
                last_ui_renderer,
                renderer,
                true,
            )
        }
    }
}

fn render_runtime_with_framebuffer<W, D>(
    output: &mut W,
    display: &mut D,
    framebuffer: &mut Framebuffer,
    ui_runtime: &mut UiRuntime,
    last_active_screen: &mut Option<UiScreen>,
    screen_model: &ScreenModel,
    last_ui_renderer: &mut String,
) -> Result<bool>
where
    W: Write,
    D: DisplayDevice,
{
    FramebufferRenderer::render_screen_model(framebuffer, screen_model);
    *last_ui_renderer = RendererMode::Framebuffer.as_str().to_string();
    display.flush_full_frame(framebuffer)?;
    emit_screen_changed_if_needed(output, last_active_screen, screen_model)?;
    ui_runtime.mark_clean();
    Ok(true)
}

#[allow(clippy::too_many_arguments)]
fn render_runtime_with_active_lvgl_or_fallback<W, D, R>(
    output: &mut W,
    errors: &mut impl Write,
    display: &mut D,
    framebuffer: &mut Framebuffer,
    ui_runtime: &mut UiRuntime,
    last_active_screen: &mut Option<UiScreen>,
    screen_model: &ScreenModel,
    last_ui_renderer: &mut String,
    renderer: &mut R,
    emit_lvgl_error: bool,
) -> Result<bool>
where
    W: Write,
    D: DisplayDevice,
    R: ActiveLvglRenderer,
{
    match renderer.render_screen_model(framebuffer, screen_model) {
        Ok(()) => {
            *last_ui_renderer = RendererMode::Lvgl.as_str().to_string();
            display.flush_full_frame(framebuffer)?;
            emit_screen_changed_if_needed(output, last_active_screen, screen_model)?;
            ui_runtime.mark_clean();
            Ok(true)
        }
        Err(err) => {
            if emit_lvgl_error {
                emit_explicit_lvgl_unavailable(output, errors, &err)?;
            }
            render_runtime_with_framebuffer(
                output,
                display,
                framebuffer,
                ui_runtime,
                last_active_screen,
                screen_model,
                last_ui_renderer,
            )
        }
    }
}

fn emit_screen_changed_if_needed<W: Write>(
    output: &mut W,
    last_active_screen: &mut Option<UiScreen>,
    screen_model: &ScreenModel,
) -> Result<()> {
    if last_active_screen
        .map(|screen| screen != screen_model.screen())
        .unwrap_or(true)
    {
        emit(
            output,
            event_envelope(
                "ui.screen_changed",
                json!({
                    "screen": screen_model.screen().as_str(),
                    "title": screen_model_title(screen_model),
                }),
            ),
        )?;
        *last_active_screen = Some(screen_model.screen());
    }
    Ok(())
}

fn emit_explicit_lvgl_unavailable<W: Write>(
    output: &mut W,
    errors: &mut impl Write,
    err: &dyn std::fmt::Display,
) -> Result<()> {
    writeln!(
        errors,
        "LVGL renderer unavailable for explicit lvgl mode: {err}"
    )?;
    emit(
        output,
        error_envelope("lvgl_unavailable", "LVGL renderer unavailable"),
    )
}

fn screen_model_title(model: &ScreenModel) -> &str {
    match model {
        ScreenModel::Hub(hub) => hub
            .cards
            .get(hub.selected_index)
            .map(|card| card.title.as_str())
            .unwrap_or("Listen"),
        ScreenModel::Listen(list)
        | ScreenModel::Playlists(list)
        | ScreenModel::RecentTracks(list)
        | ScreenModel::Talk(list)
        | ScreenModel::Contacts(list)
        | ScreenModel::CallHistory(list) => &list.title,
        ScreenModel::NowPlaying(now_playing) => &now_playing.title,
        ScreenModel::Ask(ask) => &ask.title,
        ScreenModel::TalkContact(actions) | ScreenModel::VoiceNote(actions) => &actions.title,
        ScreenModel::IncomingCall(call)
        | ScreenModel::OutgoingCall(call)
        | ScreenModel::InCall(call) => &call.title,
        ScreenModel::Power(power) => &power.title,
        ScreenModel::Loading(overlay) | ScreenModel::Error(overlay) => &overlay.title,
    }
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
