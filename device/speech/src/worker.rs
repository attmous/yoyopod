use std::io::{self, BufRead, BufReader, Cursor, Read, Write};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::sync::Arc;
use std::time::Duration;

use anyhow::{bail, Result};
use serde::de::DeserializeOwned;
use serde_json::{json, Value};

use crate::protocol::{voice_error, EnvelopeKind, WorkerEnvelope};
use crate::provider::{is_invalid_payload, new_openai_provider_from_env};
use crate::provider::{
    AskRequest, MockProvider, SpeakRequest, SpeechProvider, SpeechRequestContext, TranscribeRequest,
};

pub fn run() -> Result<()> {
    let stdin = io::stdin();
    let mut stdout = io::stdout();
    let provider = selected_provider_from_env()?;
    run_with_provider(stdin, &mut stdout, provider)
}

pub fn run_with_io<R, W>(input: R, output: &mut W) -> Result<()>
where
    R: Read,
    W: Write,
{
    let mut input = input;
    let mut buffered_input = Vec::new();
    input.read_to_end(&mut buffered_input)?;
    let provider = selected_provider_from_env()?;
    run_with_provider(Cursor::new(buffered_input), output, provider)
}

pub fn selected_provider_from_env() -> Result<Box<dyn SpeechProvider>> {
    let configured = std::env::var("YOYOPOD_VOICE_WORKER_PROVIDER")
        .unwrap_or_default()
        .trim()
        .to_ascii_lowercase();
    match configured.as_str() {
        "" | "mock" | "default" => Ok(Box::new(MockProvider)),
        "openai" => Ok(Box::new(new_openai_provider_from_env())),
        _ => bail!("unknown YOYOPOD_VOICE_WORKER_PROVIDER {configured:?}"),
    }
}

pub fn run_with_provider<R, W, P>(input: R, output: &mut W, provider: P) -> Result<()>
where
    R: Read + Send + 'static,
    W: Write,
    P: SpeechProvider + 'static,
{
    emit(
        output,
        &WorkerEnvelope::event("voice.ready", json!({ "ready": true })),
    )?;

    let provider = Arc::new(provider);
    let (work_tx, work_rx) = mpsc::channel::<WorkCompletion>();
    let input_rx = spawn_input_reader(input);
    let mut active: Option<ActiveRequest> = None;
    let mut next_generation = 0_u64;
    let mut input_closed = false;
    loop {
        drain_completed(output, &work_rx, &mut active)?;
        if input_closed {
            break;
        }
        let line = match input_rx.recv_timeout(Duration::from_millis(10)) {
            Ok(InputLine::Line(line)) => line,
            Ok(InputLine::Error(error)) => return Err(error.into()),
            Ok(InputLine::Eof) | Err(RecvTimeoutError::Disconnected) => {
                input_closed = true;
                continue;
            }
            Err(RecvTimeoutError::Timeout) => continue,
        };
        if line.trim().is_empty() {
            continue;
        }
        let envelope = match WorkerEnvelope::decode(line.as_bytes()) {
            Ok(envelope) => envelope,
            Err(error) => {
                emit(
                    output,
                    &voice_error(None, "protocol_error", error.to_string(), false),
                )?;
                continue;
            }
        };
        if envelope.kind != EnvelopeKind::Command {
            emit(
                output,
                &voice_error(
                    envelope.request_id,
                    "invalid_kind",
                    "speech worker accepts commands only",
                    false,
                ),
            )?;
            continue;
        }
        if handle_command(
            output,
            Arc::clone(&provider),
            &work_tx,
            &mut active,
            &mut next_generation,
            envelope,
        )? {
            break;
        }
    }
    while active.is_some() {
        let completion = work_rx.recv()?;
        emit_completion(output, completion, &mut active)?;
    }
    Ok(())
}

enum InputLine {
    Line(String),
    Error(io::Error),
    Eof,
}

fn spawn_input_reader<R>(input: R) -> mpsc::Receiver<InputLine>
where
    R: Read + Send + 'static,
{
    let (line_tx, line_rx) = mpsc::channel();
    std::thread::spawn(move || {
        let reader = BufReader::new(input);
        for line in reader.lines() {
            let message = match line {
                Ok(line) => InputLine::Line(line),
                Err(error) => InputLine::Error(error),
            };
            if line_tx.send(message).is_err() {
                return;
            }
        }
        let _ = line_tx.send(InputLine::Eof);
    });
    line_rx
}

struct ActiveRequest {
    request_id: Option<String>,
    generation: u64,
    kind: RequestKind,
    context: SpeechRequestContext,
    cancel_acknowledged: bool,
}

struct WorkCompletion {
    request_id: Option<String>,
    generation: u64,
    context: SpeechRequestContext,
    envelope: WorkerEnvelope,
}

struct WorkStart {
    request_id: Option<String>,
    deadline_ms: u64,
    result_type: &'static str,
    kind: RequestKind,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RequestKind {
    General,
    FocusPrompt,
}

fn handle_command<W, P>(
    output: &mut W,
    provider: Arc<P>,
    work_tx: &mpsc::Sender<WorkCompletion>,
    active: &mut Option<ActiveRequest>,
    next_generation: &mut u64,
    envelope: WorkerEnvelope,
) -> Result<bool>
where
    W: Write,
    P: SpeechProvider + 'static,
{
    let request_id = envelope.request_id.clone();
    match envelope.message_type.as_str() {
        "voice.health" => emit_result(
            output,
            "voice.health.result",
            request_id,
            provider.health(&SpeechRequestContext::new(envelope.deadline_ms)),
        )?,
        "voice.transcribe" => {
            let request = match decode_payload::<TranscribeRequest>(envelope.payload) {
                Ok(request) => request,
                Err(error) => {
                    emit(
                        output,
                        &voice_error(request_id, "invalid_payload", error.to_string(), false),
                    )?;
                    return Ok(false);
                }
            };
            start_work(
                output,
                provider,
                work_tx,
                active,
                WorkStart {
                    request_id,
                    deadline_ms: envelope.deadline_ms,
                    result_type: "voice.transcribe.result",
                    kind: RequestKind::General,
                },
                next_generation,
                move |provider, context| provider.transcribe(&context, request),
            )?;
        }
        "voice.speak" => {
            let request = match decode_payload::<SpeakRequest>(envelope.payload) {
                Ok(request) => request,
                Err(error) => {
                    emit(
                        output,
                        &voice_error(request_id, "invalid_payload", error.to_string(), false),
                    )?;
                    return Ok(false);
                }
            };
            start_work(
                output,
                provider,
                work_tx,
                active,
                WorkStart {
                    request_id,
                    deadline_ms: envelope.deadline_ms,
                    result_type: "voice.speak.result",
                    kind: RequestKind::General,
                },
                next_generation,
                move |provider, context| provider.speak(&context, request),
            )?;
        }
        "voice.focus_prompt" => {
            let request = match decode_payload::<SpeakRequest>(envelope.payload) {
                Ok(request) => request,
                Err(error) => {
                    emit(
                        output,
                        &voice_error(request_id, "invalid_payload", error.to_string(), false),
                    )?;
                    return Ok(false);
                }
            };
            if request_id.as_deref().is_none_or(str::is_empty) {
                emit(
                    output,
                    &voice_error(
                        request_id,
                        "invalid_payload",
                        "voice.focus_prompt requires request_id",
                        false,
                    ),
                )?;
                return Ok(false);
            }
            start_work(
                output,
                provider,
                work_tx,
                active,
                WorkStart {
                    request_id,
                    deadline_ms: envelope.deadline_ms,
                    result_type: "voice.focus_prompt.result",
                    kind: RequestKind::FocusPrompt,
                },
                next_generation,
                move |provider, context| provider.speak(&context, request),
            )?;
        }
        "voice.ask" => {
            let request = match decode_payload::<AskRequest>(envelope.payload) {
                Ok(request) => request,
                Err(error) => {
                    emit(
                        output,
                        &voice_error(request_id, "invalid_payload", error.to_string(), false),
                    )?;
                    return Ok(false);
                }
            };
            start_work(
                output,
                provider,
                work_tx,
                active,
                WorkStart {
                    request_id,
                    deadline_ms: envelope.deadline_ms,
                    result_type: "voice.ask.result",
                    kind: RequestKind::General,
                },
                next_generation,
                move |provider, context| provider.ask(&context, request),
            )?;
        }
        "voice.cancel" => handle_cancel(output, active, request_id, envelope.payload)?,
        "voice.cancel_focus_prompt" => handle_focus_prompt_cancel(output, active, request_id)?,
        "voice.shutdown" | "worker.stop" => {
            if let Some(active) = active.as_ref() {
                active.context.cancel();
            }
            emit(
                output,
                &WorkerEnvelope::result(
                    "voice.stopped",
                    request_id,
                    json!({ "reason": "shutdown" }),
                ),
            )?;
            return Ok(true);
        }
        _ => emit(
            output,
            &voice_error(
                request_id,
                "unknown_command",
                "unknown speech worker command",
                false,
            ),
        )?,
    }
    Ok(false)
}

fn start_work<W, P, F, T>(
    output: &mut W,
    provider: Arc<P>,
    work_tx: &mpsc::Sender<WorkCompletion>,
    active: &mut Option<ActiveRequest>,
    spec: WorkStart,
    next_generation: &mut u64,
    work: F,
) -> Result<()>
where
    W: Write,
    P: SpeechProvider + 'static,
    F: FnOnce(Arc<P>, SpeechRequestContext) -> Result<T> + Send + 'static,
    T: serde::Serialize,
{
    if active
        .as_ref()
        .is_some_and(|active| active.kind == RequestKind::General)
    {
        emit(
            output,
            &voice_error(
                spec.request_id,
                "busy",
                "speech worker is already processing a request",
                true,
            ),
        )?;
        return Ok(());
    }
    if let Some(active) = active.as_ref() {
        active.context.cancel();
    }
    *next_generation = next_generation.wrapping_add(1);
    let generation = *next_generation;
    let context = SpeechRequestContext::new(spec.deadline_ms);
    *active = Some(ActiveRequest {
        request_id: spec.request_id.clone(),
        generation,
        kind: spec.kind,
        context: context.clone(),
        cancel_acknowledged: false,
    });
    let work_tx = work_tx.clone();
    std::thread::spawn(move || {
        let result = work(Arc::clone(&provider), context.clone());
        let envelope =
            completion_envelope(spec.result_type, spec.request_id.clone(), result, &context);
        let _ = work_tx.send(WorkCompletion {
            request_id: spec.request_id,
            generation,
            context,
            envelope,
        });
    });
    Ok(())
}

fn completion_envelope<T>(
    result_type: &str,
    request_id: Option<String>,
    result: Result<T>,
    context: &SpeechRequestContext,
) -> WorkerEnvelope
where
    T: serde::Serialize,
{
    if context.is_cancelled() {
        return WorkerEnvelope::result(
            "voice.cancelled",
            request_id,
            json!({
                "cancelled": true,
                "reason": context.cancellation_reason(),
            }),
        );
    }
    match result {
        Ok(payload) => WorkerEnvelope::result(
            result_type,
            request_id,
            serde_json::to_value(payload).unwrap_or_else(|_| json!({})),
        ),
        Err(error) => provider_error_envelope(request_id, error),
    }
}

fn provider_error_envelope(request_id: Option<String>, error: anyhow::Error) -> WorkerEnvelope {
    if is_invalid_payload(&error) {
        return voice_error(request_id, "invalid_payload", error.to_string(), false);
    }
    voice_error(request_id, "provider_error", error.to_string(), true)
}

fn handle_cancel<W>(
    output: &mut W,
    active: &mut Option<ActiveRequest>,
    request_id: Option<String>,
    payload: Value,
) -> Result<()>
where
    W: Write,
{
    let requested_target_id = payload
        .get("request_id")
        .and_then(Value::as_str)
        .map(str::to_string)
        .or_else(|| request_id.clone());
    let matched = match requested_target_id.as_deref() {
        Some(target_id) => {
            active
                .as_ref()
                .and_then(|active| active.request_id.as_deref())
                == Some(target_id)
        }
        None => active.is_some(),
    };
    if matched {
        if let Some(active) = active.as_mut() {
            active.context.cancel();
            active.cancel_acknowledged = true;
        }
    }
    emit(
        output,
        &WorkerEnvelope::result(
            "voice.cancelled",
            request_id.or_else(|| requested_target_id.clone()),
            json!({
                "cancelled": matched,
                "reason": if matched { "cancel_requested" } else { "not_active" },
                "target_request_id": requested_target_id,
            }),
        ),
    )?;
    Ok(())
}

fn handle_focus_prompt_cancel<W>(
    output: &mut W,
    active: &mut Option<ActiveRequest>,
    request_id: Option<String>,
) -> Result<()>
where
    W: Write,
{
    let matched = active
        .as_ref()
        .is_some_and(|active| active.kind == RequestKind::FocusPrompt);
    if let Some(active) = active.as_mut().filter(|_| matched) {
        active.context.cancel();
        active.cancel_acknowledged = true;
    }
    emit(
        output,
        &WorkerEnvelope::result(
            "voice.focus_prompt.cancelled",
            request_id,
            json!({
                "cancelled": matched,
                "reason": if matched { "cancel_requested" } else { "not_active" },
            }),
        ),
    )?;
    Ok(())
}

fn drain_completed<W>(
    output: &mut W,
    work_rx: &mpsc::Receiver<WorkCompletion>,
    active: &mut Option<ActiveRequest>,
) -> Result<()>
where
    W: Write,
{
    while let Ok(completion) = work_rx.try_recv() {
        emit_completion(output, completion, active)?;
    }
    Ok(())
}

fn emit_completion<W>(
    output: &mut W,
    completion: WorkCompletion,
    active: &mut Option<ActiveRequest>,
) -> Result<()>
where
    W: Write,
{
    let is_active = active
        .as_ref()
        .map(|active| active.generation == completion.generation)
        .unwrap_or(false);
    let cancel_already_acknowledged = active
        .as_ref()
        .is_some_and(|active| is_active && active.cancel_acknowledged);
    if is_active {
        *active = None;
    }
    if completion.context.is_cancelled() && cancel_already_acknowledged {
        return Ok(());
    }
    if completion.context.is_cancelled() && completion.envelope.message_type != "voice.cancelled" {
        emit(
            output,
            &WorkerEnvelope::result(
                "voice.cancelled",
                completion.request_id,
                json!({
                    "cancelled": true,
                    "reason": completion.context.cancellation_reason(),
                }),
            ),
        )?;
    } else {
        emit(output, &completion.envelope)?;
    }
    Ok(())
}

fn decode_payload<T>(payload: Value) -> Result<T>
where
    T: DeserializeOwned,
{
    Ok(serde_json::from_value(payload)?)
}

fn emit_result<W, T>(
    output: &mut W,
    message_type: &str,
    request_id: Option<String>,
    result: Result<T>,
) -> Result<()>
where
    W: Write,
    T: serde::Serialize,
{
    match result {
        Ok(payload) => emit(
            output,
            &WorkerEnvelope::result(message_type, request_id, serde_json::to_value(payload)?),
        ),
        Err(error) => emit(output, &provider_error_envelope(request_id, error)),
    }
}

fn emit<W>(output: &mut W, envelope: &WorkerEnvelope) -> Result<()>
where
    W: Write,
{
    output.write_all(&envelope.encode()?)?;
    output.flush()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn work_start(request_id: &str, kind: RequestKind) -> WorkStart {
        WorkStart {
            request_id: Some(request_id.to_string()),
            deadline_ms: 5_000,
            result_type: "voice.focus_prompt.result",
            kind,
        }
    }

    #[test]
    fn newer_focus_prompt_preempts_the_previous_generation() {
        let provider = Arc::new(MockProvider);
        let (work_tx, _work_rx) = mpsc::channel();
        let mut active = None;
        let mut generation = 0;
        let mut output = Vec::new();

        start_work(
            &mut output,
            Arc::clone(&provider),
            &work_tx,
            &mut active,
            work_start("focus-1", RequestKind::FocusPrompt),
            &mut generation,
            |_, _| Ok(json!({"audio_path": "first.wav"})),
        )
        .unwrap();
        let first_context = active.as_ref().unwrap().context.clone();

        start_work(
            &mut output,
            provider,
            &work_tx,
            &mut active,
            work_start("focus-2", RequestKind::FocusPrompt),
            &mut generation,
            |_, _| Ok(json!({"audio_path": "second.wav"})),
        )
        .unwrap();

        assert!(first_context.is_cancelled());
        assert_eq!(
            active.as_ref().unwrap().request_id.as_deref(),
            Some("focus-2")
        );
        assert_eq!(active.as_ref().unwrap().generation, 2);
        assert!(output.is_empty());
    }

    #[test]
    fn focus_prompt_never_interrupts_general_speech_work() {
        let provider = Arc::new(MockProvider);
        let (work_tx, _work_rx) = mpsc::channel();
        let mut active = None;
        let mut generation = 0;
        let mut output = Vec::new();

        start_work(
            &mut output,
            Arc::clone(&provider),
            &work_tx,
            &mut active,
            work_start("ask", RequestKind::General),
            &mut generation,
            |_, _| Ok(json!({"answer": "hello"})),
        )
        .unwrap();
        start_work(
            &mut output,
            provider,
            &work_tx,
            &mut active,
            work_start("focus", RequestKind::FocusPrompt),
            &mut generation,
            |_, _| Ok(json!({"audio_path": "focus.wav"})),
        )
        .unwrap();

        assert_eq!(active.as_ref().unwrap().request_id.as_deref(), Some("ask"));
        let envelope = WorkerEnvelope::decode(&output).unwrap();
        assert_eq!(envelope.message_type, "voice.error");
        assert_eq!(envelope.payload["code"], "busy");
    }

    #[test]
    fn cancel_without_request_id_cancels_the_single_active_request() {
        let context = SpeechRequestContext::new(5_000);
        let mut active = Some(ActiveRequest {
            request_id: None,
            generation: 1,
            kind: RequestKind::General,
            context: context.clone(),
            cancel_acknowledged: false,
        });
        let mut output = Vec::new();

        handle_cancel(&mut output, &mut active, None, json!({})).unwrap();

        assert!(context.is_cancelled());
        assert!(active.as_ref().unwrap().cancel_acknowledged);
        let envelope = WorkerEnvelope::decode(&output).unwrap();
        assert_eq!(envelope.message_type, "voice.cancelled");
        assert_eq!(envelope.payload["cancelled"], true);
    }
}
