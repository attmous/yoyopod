use std::io::{Read, Write};
use std::sync::mpsc::RecvTimeoutError;
use std::time::{Duration, Instant};

use anyhow::Result;
use yoyopod_protocol::ui::{
    UiError, UiErrorCode, UiEvent, UiHealth, UiScreen, UiScreenChanged, UiScreenshotCaptured,
};

use crate::application::UiRuntime;
use crate::engine::Engine;
use crate::hardware::{ButtonDevice, DisplayDevice};
use crate::input::{ButtonTiming, OneButtonMachine};
use crate::renderer::{Framebuffer, LvglRenderer, Renderer};
use crate::router;
use crate::scene::load_scene_defaults;
use crate::screenshot::{self, Rgb565Image};
use crate::transport::{codec, dispatcher, handshake, inbound, outbound};
use crate::RenderMode;

const MANAGER_HEARTBEAT_TIMEOUT: Duration = Duration::from_secs(15);
const RUNTIME_TICK_TIMEOUT: Duration = Duration::from_secs(5);
const INPUT_POLL_INTERVAL: Duration = Duration::from_millis(250);

pub struct RenderState {
    framebuffer: Framebuffer,
    engine: Engine,
    renderer: Box<LvglRenderer>,
    frames: usize,
    last_active_screen: Option<UiScreen>,
    last_ui_renderer: String,
}

impl RenderState {
    pub fn open(width: usize, height: usize) -> Result<Self> {
        router::validate_routes()?;
        load_scene_defaults()?;
        let framebuffer = Framebuffer::new(width, height);
        let mut renderer = Box::new(LvglRenderer::open(None)?);
        renderer.initialize_display(&framebuffer)?;
        Ok(Self {
            framebuffer,
            engine: Engine::default(),
            renderer,
            frames: 0,
            last_active_screen: None,
            last_ui_renderer: String::new(),
        })
    }

    pub fn frames(&self) -> usize {
        self.frames
    }

    pub fn last_ui_renderer(&self) -> &str {
        &self.last_ui_renderer
    }

    pub fn capture_screenshot(
        &mut self,
        path: &str,
        prefer_readback: bool,
    ) -> UiScreenshotCaptured {
        let renderer = &mut self.renderer;
        let framebuffer = &self.framebuffer;
        screenshot::capture(
            || renderer.readback_rgb565(),
            || Ok(Rgb565Image::from_framebuffer(framebuffer)),
            path,
            prefer_readback,
        )
    }
}

pub fn run_worker<R, W, E, D, B>(
    input: R,
    output: &mut W,
    errors: &mut E,
    mut display: D,
    mut button: B,
) -> Result<()>
where
    R: Read + Send + 'static,
    W: Write,
    E: Write,
    D: DisplayDevice,
    B: ButtonDevice,
{
    let mut input_events = 0usize;
    let mut button_machine = OneButtonMachine::new(ButtonTiming::default());
    let status_bar_preview = status_bar_preview_enabled();
    if status_bar_preview {
        writeln!(
            errors,
            "status-bar hardware preview enabled via YOYOPOD_UI_STATUS_BAR_PREVIEW"
        )?;
    }
    let mut ui_runtime = UiRuntime::with_status_bar_preview(status_bar_preview);
    let mut render_state = RenderState::open(display.width(), display.height())?;
    let mut shutdown_complete_emitted = false;
    let mut watchdog = RuntimeWatchdog::new();

    handshake::emit_ready(output, display.width(), display.height())?;

    let lines = codec::spawn_line_reader(input);
    loop {
        let line = match lines.recv_timeout(INPUT_POLL_INTERVAL) {
            Ok(line) => {
                watchdog.note_manager_message();
                line?
            }
            Err(RecvTimeoutError::Timeout) => {
                if watchdog.manager_timed_out() {
                    handshake::emit_manager_timeout(output, errors, MANAGER_HEARTBEAT_TIMEOUT)?;
                    break;
                }
                emit_runtime_stalled_if_needed(
                    output,
                    &mut display,
                    &mut ui_runtime,
                    &mut render_state,
                    &mut watchdog,
                )?;
                continue;
            }
            Err(RecvTimeoutError::Disconnected) => break,
        };
        if line.trim().is_empty() {
            continue;
        }

        let envelope = match codec::decode_envelope(&line) {
            Ok(envelope) => envelope,
            Err(err) => {
                writeln!(errors, "protocol decode error: {err}")?;
                outbound::emit_event(
                    output,
                    UiEvent::Error(UiError::new(UiErrorCode::DecodeError, err.to_string())),
                )?;
                continue;
            }
        };

        let command = match inbound::decode_command(envelope) {
            Ok(command) => command,
            Err(err) => {
                writeln!(errors, "UI command decode error: {err}")?;
                outbound::emit_event(
                    output,
                    UiEvent::Error(UiError::new(UiErrorCode::InvalidCommand, err.to_string())),
                )?;
                continue;
            }
        };

        let outcome = dispatcher::dispatch_command(command);
        if matches!(outcome.event, dispatcher::AppEvent::Tick) {
            watchdog.note_tick();
        }
        let mut context = AppEventContext {
            output,
            display: &mut display,
            button: &mut button,
            ui_runtime: &mut ui_runtime,
            button_machine: &mut button_machine,
            render_state: &mut render_state,
            input_events: &mut input_events,
        };
        if handle_app_event(outcome.event, &mut context)? {
            shutdown_complete_emitted = true;
            break;
        }
        emit_runtime_stalled_if_needed(
            output,
            &mut display,
            &mut ui_runtime,
            &mut render_state,
            &mut watchdog,
        )?;
    }

    if !shutdown_complete_emitted {
        handshake::emit_shutdown_complete(output)?;
    }

    Ok(())
}

struct RuntimeWatchdog {
    last_manager_message: Instant,
    last_tick: Instant,
    runtime_stalled_emitted: bool,
}

impl RuntimeWatchdog {
    fn new() -> Self {
        let now = Instant::now();
        Self {
            last_manager_message: now,
            last_tick: now,
            runtime_stalled_emitted: false,
        }
    }

    fn note_manager_message(&mut self) {
        self.last_manager_message = Instant::now();
    }

    fn note_tick(&mut self) {
        self.last_tick = Instant::now();
        self.runtime_stalled_emitted = false;
    }

    fn manager_timed_out(&self) -> bool {
        self.last_manager_message.elapsed() >= MANAGER_HEARTBEAT_TIMEOUT
    }

    fn runtime_stalled(&self) -> bool {
        self.last_tick.elapsed() >= RUNTIME_TICK_TIMEOUT && !self.runtime_stalled_emitted
    }
}

fn emit_runtime_stalled_if_needed<W, D>(
    output: &mut W,
    display: &mut D,
    ui_runtime: &mut UiRuntime,
    render_state: &mut RenderState,
    watchdog: &mut RuntimeWatchdog,
) -> Result<()>
where
    W: Write,
    D: DisplayDevice,
{
    if !watchdog.runtime_stalled() {
        return Ok(());
    }
    watchdog.runtime_stalled_emitted = true;
    ui_runtime.mark_runtime_stalled();
    outbound::emit_event(
        output,
        UiEvent::Error(UiError::new(
            UiErrorCode::RuntimeStalled,
            "runtime tick stalled",
        )),
    )?;
    if let Some(event) = render_if_dirty(
        ui_runtime,
        display,
        render_state,
        outbound::monotonic_millis(),
    )? {
        outbound::emit_event(output, event)?;
    }
    Ok(())
}

struct AppEventContext<'a, W, D, B> {
    output: &'a mut W,
    display: &'a mut D,
    button: &'a mut B,
    ui_runtime: &'a mut UiRuntime,
    button_machine: &'a mut OneButtonMachine,
    render_state: &'a mut RenderState,
    input_events: &'a mut usize,
}

fn handle_app_event<W, D, B>(
    event: dispatcher::AppEvent,
    context: &mut AppEventContext<'_, W, D, B>,
) -> Result<bool>
where
    W: Write,
    D: DisplayDevice,
    B: ButtonDevice,
{
    match event {
        dispatcher::AppEvent::SetBacklight { brightness } => {
            context.display.set_backlight(brightness)?;
        }
        dispatcher::AppEvent::RuntimeSnapshot(snapshot) => {
            context.ui_runtime.apply_snapshot(snapshot);
        }
        dispatcher::AppEvent::RuntimePatch(patch) => {
            context.ui_runtime.apply_patch(patch);
        }
        dispatcher::AppEvent::InputAction(action) => {
            *context.input_events += 1;
            let now_ms = outbound::monotonic_millis();
            outbound::emit_input_action(context.output, action, "command", now_ms, 0)?;
            context.ui_runtime.handle_input(action, now_ms);
            outbound::emit_intents(context.output, context.ui_runtime.take_intents())?;
        }
        dispatcher::AppEvent::Tick => {
            let now_ms = outbound::monotonic_millis();
            context.ui_runtime.advance_status_bar(now_ms);
            context.ui_runtime.advance_animations(now_ms);
            context.ui_runtime.advance_home_state(now_ms);
            if context.render_state.engine.animation_frame_dirty(now_ms) {
                context.ui_runtime.mark_animation_frame();
            }
            handle_button_input(
                context.output,
                context.button,
                context.button_machine,
                context.ui_runtime,
                context.input_events,
                now_ms,
            )?;
            outbound::emit_intents(context.output, context.ui_runtime.take_intents())?;
        }
        dispatcher::AppEvent::PollInput => {
            let now_ms = outbound::monotonic_millis();
            handle_button_input(
                context.output,
                context.button,
                context.button_machine,
                context.ui_runtime,
                context.input_events,
                now_ms,
            )?;
            outbound::emit_intents(context.output, context.ui_runtime.take_intents())?;
        }
        dispatcher::AppEvent::Health => {
            outbound::emit_event(
                context.output,
                health_event(
                    context.ui_runtime,
                    context.render_state,
                    *context.input_events,
                ),
            )?;
        }
        dispatcher::AppEvent::Animate(request) => {
            context
                .ui_runtime
                .start_animation(request, outbound::monotonic_millis());
        }
        dispatcher::AppEvent::Screenshot {
            path,
            prefer_readback,
        } => {
            let captured = context
                .render_state
                .capture_screenshot(&path, prefer_readback);
            outbound::emit_event(context.output, UiEvent::ScreenshotCaptured(captured))?;
        }
        dispatcher::AppEvent::Shutdown => {
            handshake::emit_shutdown_complete(context.output)?;
            return Ok(true);
        }
    }

    if let Some(event) = render_if_dirty(
        context.ui_runtime,
        context.display,
        context.render_state,
        outbound::monotonic_millis(),
    )? {
        outbound::emit_event(context.output, event)?;
    }
    Ok(false)
}

fn status_bar_preview_enabled() -> bool {
    std::env::var("YOYOPOD_UI_STATUS_BAR_PREVIEW")
        .ok()
        .is_some_and(|value| {
            matches!(
                value.trim().to_ascii_lowercase().as_str(),
                "1" | "true" | "yes" | "on" | "cycle"
            )
        })
}

fn handle_button_input<W, B>(
    output: &mut W,
    button: &mut B,
    button_machine: &mut OneButtonMachine,
    ui_runtime: &mut UiRuntime,
    input_events: &mut usize,
    now_ms: u64,
) -> Result<()>
where
    W: Write,
    B: ButtonDevice,
{
    let button_events = crate::input::poll_button_actions(
        button,
        button_machine,
        ui_runtime.wants_ptt_passthrough(),
        now_ms,
    )?;
    if button_machine.debounced_pressed() && ui_runtime.wake_home_from_ambient(now_ms) {
        button_machine.cancel_current_gesture();
        return Ok(());
    }
    for event in button_events {
        *input_events += 1;
        outbound::emit_input_action(
            output,
            event.action,
            event.method,
            event.timestamp_ms,
            event.duration_ms,
        )?;
        ui_runtime.handle_input(event.action, now_ms);
    }
    Ok(())
}

fn render_if_dirty<D>(
    ui_runtime: &mut UiRuntime,
    display: &mut D,
    render: &mut RenderState,
    now_ms: u64,
) -> Result<Option<UiEvent>>
where
    D: DisplayDevice,
{
    let Some(frame) = ui_runtime.frame_request(now_ms) else {
        return Ok(None);
    };
    let outcome = render.engine.tick(
        &frame.scene_graph,
        frame.dirty_region,
        router::status_bar_region(),
        now_ms,
    );
    render.renderer.apply(outcome.mutations)?;
    let report = render
        .renderer
        .flush(&mut render.framebuffer, outcome.mode)?;
    render.last_ui_renderer = report.renderer.to_string();
    match report.mode {
        RenderMode::FullFrame => display.flush_full_frame(&render.framebuffer)?,
        RenderMode::HudRegion => {
            display.flush_region(&render.framebuffer, router::status_bar_region())?
        }
        RenderMode::Region(region) => display.flush_region(&render.framebuffer, region)?,
    }
    let screen_changed = screen_changed_if_needed(&mut render.last_active_screen, ui_runtime);
    ui_runtime.mark_clean();
    render.frames += 1;
    Ok(screen_changed)
}

fn health_event(ui_runtime: &UiRuntime, render: &RenderState, button_events: usize) -> UiEvent {
    UiEvent::Health(UiHealth {
        frames: render.frames(),
        button_events,
        last_ui_renderer: render.last_ui_renderer().to_string(),
        active_screen: ui_runtime.active_screen(),
        full_snapshots: ui_runtime.full_snapshots,
        patches_per_domain: ui_runtime.patches_per_domain.clone(),
    })
}

fn screen_changed_if_needed(
    last_active_screen: &mut Option<UiScreen>,
    ui_runtime: &UiRuntime,
) -> Option<UiEvent> {
    let active_screen = ui_runtime.active_screen();
    if last_active_screen
        .map(|screen| screen != active_screen)
        .unwrap_or(true)
    {
        let event = Some(UiEvent::ScreenChanged(UiScreenChanged {
            screen: active_screen,
            title: ui_runtime.active_title(),
        }));
        *last_active_screen = Some(active_screen);
        return event;
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Default)]
    struct TestButton {
        pressed: bool,
    }

    impl ButtonDevice for TestButton {
        fn pressed(&mut self) -> Result<bool> {
            Ok(self.pressed)
        }
    }

    fn sample_button(
        button: &mut TestButton,
        machine: &mut OneButtonMachine,
        runtime: &mut UiRuntime,
        output: &mut Vec<u8>,
        input_events: &mut usize,
        pressed: bool,
        now_ms: u64,
    ) {
        button.pressed = pressed;
        handle_button_input(output, button, machine, runtime, input_events, now_ms).unwrap();
    }

    fn deliberate_short_press(
        button: &mut TestButton,
        machine: &mut OneButtonMachine,
        runtime: &mut UiRuntime,
        output: &mut Vec<u8>,
        input_events: &mut usize,
        started_ms: u64,
    ) {
        sample_button(
            button,
            machine,
            runtime,
            output,
            input_events,
            true,
            started_ms,
        );
        sample_button(
            button,
            machine,
            runtime,
            output,
            input_events,
            true,
            started_ms + 50,
        );
        sample_button(
            button,
            machine,
            runtime,
            output,
            input_events,
            false,
            started_ms + 250,
        );
        sample_button(
            button,
            machine,
            runtime,
            output,
            input_events,
            false,
            started_ms + 300,
        );
        sample_button(
            button,
            machine,
            runtime,
            output,
            input_events,
            false,
            started_ms + 600,
        );
    }

    #[test]
    fn physical_deliberate_short_presses_cycle_home_deck_focus() {
        let mut button = TestButton::default();
        let mut machine = OneButtonMachine::new(ButtonTiming::default());
        let mut runtime = UiRuntime::default();
        let mut output = Vec::new();
        let mut input_events = 0;

        for (started_ms, expected_focus) in [(0, 0), (700, 1), (1_400, 2), (2_100, 3), (2_800, 0)] {
            deliberate_short_press(
                &mut button,
                &mut machine,
                &mut runtime,
                &mut output,
                &mut input_events,
                started_ms,
            );
            assert_eq!(runtime.focus_index, expected_focus);
            assert_eq!(runtime.active_screen(), UiScreen::Hub);
        }

        assert_eq!(input_events, 5);
        let emitted = String::from_utf8(output)
            .unwrap()
            .lines()
            .map(|line| yoyopod_protocol::WorkerEnvelope::decode(line.as_bytes()).unwrap())
            .collect::<Vec<_>>();
        assert_eq!(emitted.len(), 5);
        assert!(emitted
            .iter()
            .all(|envelope| envelope.message_type == "ui.input"));
    }

    #[test]
    fn physical_hold_on_focused_record_emits_ptt_press_and_release() {
        let mama = yoyopod_protocol::ui::ListItemSnapshot::new(
            "sip:mama@example.test",
            "Mama",
            "",
            "mono:M",
        );
        let mut button = TestButton::default();
        let mut machine = OneButtonMachine::new(ButtonTiming::default());
        let mut runtime = UiRuntime::default();
        runtime.snapshot.call.contacts = vec![mama.clone()];
        runtime.selected_contact = Some(mama);
        runtime.active_screen = UiScreen::TalkContact;
        runtime.focus_index = 1;
        let mut output = Vec::new();
        let mut input_events = 0;

        sample_button(
            &mut button,
            &mut machine,
            &mut runtime,
            &mut output,
            &mut input_events,
            true,
            0,
        );
        sample_button(
            &mut button,
            &mut machine,
            &mut runtime,
            &mut output,
            &mut input_events,
            true,
            50,
        );
        sample_button(
            &mut button,
            &mut machine,
            &mut runtime,
            &mut output,
            &mut input_events,
            true,
            400,
        );
        assert!(matches!(
            runtime.take_intents().as_slice(),
            [yoyopod_protocol::ui::UiIntent::Voice(
                yoyopod_protocol::ui::VoiceIntent::CaptureStartAndSend(_)
            )]
        ));

        runtime.snapshot.voice.phase = "recording".to_string();
        runtime.snapshot.voice.capture_in_flight = true;
        runtime.snapshot.voice.ptt_active = true;
        sample_button(
            &mut button,
            &mut machine,
            &mut runtime,
            &mut output,
            &mut input_events,
            false,
            1_000,
        );
        sample_button(
            &mut button,
            &mut machine,
            &mut runtime,
            &mut output,
            &mut input_events,
            false,
            1_050,
        );
        assert_eq!(
            runtime.take_intents(),
            vec![yoyopod_protocol::ui::UiIntent::Voice(
                yoyopod_protocol::ui::VoiceIntent::CaptureStop,
            )]
        );
        assert_eq!(input_events, 2);
    }

    #[test]
    fn physical_hold_on_ask_emits_start_then_stop_without_navigating_home() {
        let mut button = TestButton::default();
        let mut machine = OneButtonMachine::new(ButtonTiming::default());
        let mut runtime = UiRuntime::default();
        runtime.active_screen = UiScreen::Ask;
        runtime.snapshot.network.connected = true;
        let mut output = Vec::new();
        let mut input_events = 0;

        for (pressed, now_ms) in [(true, 0), (true, 50), (true, 400)] {
            sample_button(
                &mut button,
                &mut machine,
                &mut runtime,
                &mut output,
                &mut input_events,
                pressed,
                now_ms,
            );
        }
        assert_eq!(
            runtime.take_intents(),
            vec![yoyopod_protocol::ui::UiIntent::Voice(
                yoyopod_protocol::ui::VoiceIntent::AskStart,
            )]
        );

        runtime.snapshot.voice.phase = "listening".to_string();
        runtime.snapshot.voice.capture_in_flight = true;
        runtime.snapshot.voice.ptt_active = true;
        for (pressed, now_ms) in [(false, 1_000), (false, 1_050)] {
            sample_button(
                &mut button,
                &mut machine,
                &mut runtime,
                &mut output,
                &mut input_events,
                pressed,
                now_ms,
            );
        }
        assert_eq!(
            runtime.take_intents(),
            vec![yoyopod_protocol::ui::UiIntent::Voice(
                yoyopod_protocol::ui::VoiceIntent::AskStop,
            )]
        );
        assert_eq!(runtime.active_screen(), UiScreen::Ask);
        assert_eq!(input_events, 2);
    }
}
