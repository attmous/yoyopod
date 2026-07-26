use std::io::Write;

use anyhow::Result;
use yoyopod_protocol::ui::{InputAction, UiEvent, UiInputEvent, UiIntent};
use yoyopod_protocol::WorkerEnvelope;

use super::codec;

fn emit<W: Write>(output: &mut W, envelope: WorkerEnvelope) -> Result<()> {
    output.write_all(&codec::encode_envelope(&envelope)?)?;
    output.flush()?;
    Ok(())
}

pub(crate) fn emit_event<W: Write>(output: &mut W, event: UiEvent) -> Result<()> {
    let mut envelope = event.into_envelope();
    envelope.timestamp_ms = monotonic_millis();
    emit(output, envelope)
}

pub(crate) fn emit_intents<W: Write>(output: &mut W, intents: Vec<UiIntent>) -> Result<()> {
    for intent in intents {
        emit_event(output, UiEvent::Intent(intent))?;
    }
    Ok(())
}

pub(crate) fn emit_accessibility_events<W: Write>(
    output: &mut W,
    events: Vec<UiEvent>,
) -> Result<()> {
    for event in events {
        debug_assert!(matches!(
            event,
            UiEvent::FocusChanged(_) | UiEvent::FocusCleared
        ));
        emit_event(output, event)?;
    }
    Ok(())
}

pub(crate) fn emit_input_action<W: Write>(
    output: &mut W,
    action: InputAction,
    method: impl Into<String>,
    timestamp_ms: u64,
    duration_ms: u64,
) -> Result<()> {
    emit_event(
        output,
        UiEvent::Input(UiInputEvent {
            action,
            method: method.into(),
            timestamp_ms,
            duration_ms,
        }),
    )
}

pub(crate) fn monotonic_millis() -> u64 {
    use std::sync::OnceLock;
    use std::time::Instant;

    static START: OnceLock<Instant> = OnceLock::new();
    START.get_or_init(Instant::now).elapsed().as_millis() as u64
}
