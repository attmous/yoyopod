use anyhow::Result;
use serde_json::Value;
use std::collections::VecDeque;
use std::io::{self, Read, Write};
use std::sync::{Arc, Condvar, Mutex, OnceLock};
use std::thread;
use std::time::{Duration, Instant};
use yoyopod_speech_host::provider::{
    invalid_payload, AskRequest, AskResult, HealthResult, MockProvider, SpeakRequest, SpeakResult,
    SpeechProvider, SpeechRequestContext, TranscribeRequest, TranscribeResult,
};
use yoyopod_speech_host::worker::{run_with_io, run_with_provider, selected_provider_from_env};

#[test]
fn mock_worker_handles_health_transcribe_ask_and_speak() {
    let _lock = env_lock()
        .lock()
        .unwrap_or_else(|poison| poison.into_inner());
    let _guard = EnvGuard::new(&[
        "YOYOPOD_VOICE_WORKER_PROVIDER",
        "YOYOPOD_MOCK_TRANSCRIPT",
        "YOYOPOD_MOCK_ASK_ANSWER",
    ]);
    std::env::set_var("YOYOPOD_VOICE_WORKER_PROVIDER", "mock");
    std::env::set_var("YOYOPOD_MOCK_TRANSCRIPT", "ask what is saturn");
    std::env::set_var(
        "YOYOPOD_MOCK_ASK_ANSWER",
        "Saturn is the planet with bright rings.",
    );

    let transcribe_input = concat!(
        r#"{"schema_version":1,"kind":"command","type":"voice.health","request_id":"health-1","payload":{}}"#,
        "\n",
        r#"{"schema_version":1,"kind":"command","type":"voice.transcribe","request_id":"stt-1","payload":{"audio_path":"/tmp/input.wav","format":"wav","sample_rate_hz":16000,"channels":1}}"#,
        "\n",
    );
    let mut output = Vec::new();

    run_with_io(transcribe_input.as_bytes(), &mut output).expect("run speech worker");
    let envelopes = decode_lines(&output);

    assert_eq!(envelopes[0]["kind"], "event");
    assert_eq!(envelopes[0]["type"], "voice.ready");
    assert_eq!(
        find(&envelopes, "voice.health.result")["payload"]["provider"],
        "mock"
    );
    assert_eq!(
        find(&envelopes, "voice.transcribe.result")["payload"]["text"],
        "ask what is saturn"
    );
    let ask_input = concat!(
        r#"{"schema_version":1,"kind":"command","type":"voice.ask","request_id":"ask-1","payload":{"question":"what is saturn","model":"mock-ask","history":[{"role":"user","text":"hello"}]}}"#,
        "\n",
    );
    let mut output = Vec::new();

    run_with_io(ask_input.as_bytes(), &mut output).expect("run speech worker");
    let envelopes = decode_lines(&output);
    assert_eq!(
        find(&envelopes, "voice.ask.result")["payload"]["answer"],
        "Saturn is the planet with bright rings."
    );
    let speak_input = concat!(
        r#"{"schema_version":1,"kind":"command","type":"voice.speak","request_id":"tts-1","payload":{"text":"hello","sample_rate_hz":16000}}"#,
        "\n",
    );
    let mut output = Vec::new();

    run_with_io(speak_input.as_bytes(), &mut output).expect("run speech worker");
    let envelopes = decode_lines(&output);
    let speak = find(&envelopes, "voice.speak.result");
    assert_eq!(speak["payload"]["format"], "wav");
    assert_eq!(speak["payload"]["sample_rate_hz"], 16000);
    assert!(speak["payload"]["audio_path"]
        .as_str()
        .expect("audio path")
        .contains("yoyopod-mock-tts-"));
}

#[test]
fn worker_rejects_non_command_envelopes() {
    let _lock = env_lock()
        .lock()
        .unwrap_or_else(|poison| poison.into_inner());
    let _guard = EnvGuard::new(&["YOYOPOD_VOICE_WORKER_PROVIDER"]);
    std::env::set_var("YOYOPOD_VOICE_WORKER_PROVIDER", "mock");
    let input =
        br#"{"schema_version":1,"kind":"event","type":"voice.health","request_id":"bad-1","payload":{}}
"#;
    let mut output = Vec::new();

    run_with_io(&input[..], &mut output).expect("run speech worker");
    let envelopes = decode_lines(&output);
    let error = find(&envelopes, "voice.error");

    assert_eq!(error["kind"], "error");
    assert_eq!(error["request_id"], "bad-1");
    assert_eq!(error["payload"]["code"], "invalid_kind");
}

#[test]
fn worker_selects_openai_provider_from_env() {
    let _lock = env_lock()
        .lock()
        .unwrap_or_else(|poison| poison.into_inner());
    let _guard = EnvGuard::new(&["YOYOPOD_VOICE_WORKER_PROVIDER", "OPENAI_API_KEY"]);
    std::env::set_var("YOYOPOD_VOICE_WORKER_PROVIDER", " OPENAI ");
    std::env::remove_var("OPENAI_API_KEY");
    let input =
        br#"{"schema_version":1,"kind":"command","type":"voice.health","request_id":"health-1","payload":{}}
"#;
    let mut output = Vec::new();

    run_with_io(&input[..], &mut output).expect("run speech worker");
    let envelopes = decode_lines(&output);
    let error = find(&envelopes, "voice.error");

    assert_eq!(error["request_id"], "health-1");
    assert!(error["payload"]["message"]
        .as_str()
        .expect("error message")
        .contains("OPENAI_API_KEY"));
}

#[test]
fn selected_provider_rejects_unknown_env_value() {
    let _lock = env_lock()
        .lock()
        .unwrap_or_else(|poison| poison.into_inner());
    let _guard = EnvGuard::new(&["YOYOPOD_VOICE_WORKER_PROVIDER"]);
    std::env::set_var("YOYOPOD_VOICE_WORKER_PROVIDER", "bogus");

    let error = match selected_provider_from_env() {
        Ok(_) => panic!("unknown provider should fail"),
        Err(error) => error,
    };

    assert!(error
        .to_string()
        .contains("unknown YOYOPOD_VOICE_WORKER_PROVIDER"));
}

#[test]
fn worker_rejects_concurrent_active_work_as_busy() {
    let provider = BlockingProvider::new();
    let input = concat!(
        r#"{"schema_version":1,"kind":"command","type":"voice.transcribe","request_id":"req-active","deadline_ms":1000,"payload":{"audio_path":"/tmp/input.wav","sample_rate_hz":16000}}"#,
        "\n",
        r#"{"schema_version":1,"kind":"command","type":"voice.speak","request_id":"req-busy","deadline_ms":1000,"payload":{"text":"hello","sample_rate_hz":16000}}"#,
        "\n",
    );
    let provider_for_thread = provider.clone();
    let output = Arc::new(Mutex::new(Vec::new()));
    let output_for_thread = Arc::clone(&output);
    let done = thread::spawn(move || {
        let mut output = output_for_thread.lock().expect("output lock");
        run_with_provider(input.as_bytes(), &mut *output, provider_for_thread)
    });

    provider.wait_entered();
    provider.release();
    done.join()
        .expect("worker thread joins")
        .expect("worker succeeds");
    let output = output.lock().expect("output lock");
    let envelopes = decode_lines(&output);
    let busy = find(&envelopes, "voice.error");

    assert_eq!(busy["request_id"], "req-busy");
    assert_eq!(busy["payload"]["code"], "busy");
    assert_eq!(busy["payload"]["retryable"], true);
    find(&envelopes, "voice.transcribe.result");
}

#[test]
fn worker_cancel_emits_cancelled_ack_for_active_request() {
    let provider = BlockingProvider::new();
    let input = concat!(
        r#"{"schema_version":1,"kind":"command","type":"voice.transcribe","request_id":"req-active","deadline_ms":1000,"payload":{"audio_path":"/tmp/input.wav"}}"#,
        "\n",
        r#"{"schema_version":1,"kind":"command","type":"voice.cancel","request_id":"req-cancel","payload":{"request_id":"req-active"}}"#,
        "\n",
    );
    let provider_for_thread = provider.clone();
    let output = Arc::new(Mutex::new(Vec::new()));
    let output_for_thread = Arc::clone(&output);
    let done = thread::spawn(move || {
        let mut output = output_for_thread.lock().expect("output lock");
        run_with_provider(input.as_bytes(), &mut *output, provider_for_thread)
    });

    provider.wait_entered();
    provider.release();
    done.join()
        .expect("worker thread joins")
        .expect("worker succeeds");
    let output = output.lock().expect("output lock");
    let envelopes = decode_lines(&output);
    let cancelled = find(&envelopes, "voice.cancelled");

    assert_eq!(cancelled["request_id"], "req-cancel");
    assert_eq!(cancelled["payload"]["cancelled"], true);
    assert_eq!(cancelled["payload"]["target_request_id"], "req-active");
}

#[test]
fn worker_cancel_ack_suppresses_late_provider_cancelled_result() {
    let provider = BlockingProvider::new();
    let input = concat!(
        r#"{"schema_version":1,"kind":"command","type":"voice.transcribe","request_id":"req-active","deadline_ms":1000,"payload":{"audio_path":"/tmp/input.wav"}}"#,
        "\n",
        r#"{"schema_version":1,"kind":"command","type":"voice.cancel","request_id":"req-cancel","payload":{"request_id":"req-active"}}"#,
        "\n",
    );
    let provider_for_thread = provider.clone();
    let output = Arc::new(Mutex::new(Vec::new()));
    let output_for_thread = Arc::clone(&output);
    let done = thread::spawn(move || {
        let mut output = output_for_thread.lock().expect("output lock");
        run_with_provider(input.as_bytes(), &mut *output, provider_for_thread)
    });

    provider.wait_entered();
    provider.release();
    done.join()
        .expect("worker thread joins")
        .expect("worker succeeds");
    let output = output.lock().expect("output lock");
    let envelopes = decode_lines(&output);
    let cancelled: Vec<_> = envelopes
        .iter()
        .filter(|envelope| envelope["type"] == "voice.cancelled")
        .collect();

    assert_eq!(cancelled.len(), 1, "cancel envelopes: {cancelled:#?}");
    assert_eq!(cancelled[0]["request_id"], "req-cancel");
    assert_eq!(cancelled[0]["payload"]["reason"], "cancel_requested");
}

#[test]
fn worker_cancel_uses_cancel_request_id_when_target_is_not_active() {
    let input =
        br#"{"schema_version":1,"kind":"command","type":"voice.cancel","request_id":"req-cancel","payload":{"request_id":"req-missing"}}
"#;
    let mut output = Vec::new();

    run_with_provider(&input[..], &mut output, BlockingProvider::new()).expect("worker succeeds");
    let envelopes = decode_lines(&output);
    let cancelled = find(&envelopes, "voice.cancelled");

    assert_eq!(cancelled["request_id"], "req-cancel");
    assert_eq!(cancelled["payload"]["cancelled"], false);
    assert_eq!(cancelled["payload"]["reason"], "not_active");
    assert_eq!(cancelled["payload"]["target_request_id"], "req-missing");
}

#[test]
fn worker_deadline_emits_cancelled_result() {
    let provider = DeadlineAwareProvider;
    let input =
        br#"{"schema_version":1,"kind":"command","type":"voice.transcribe","request_id":"req-expired","deadline_ms":1,"payload":{"audio_path":"/tmp/input.wav"}}
"#;
    let mut output = Vec::new();

    run_with_provider(&input[..], &mut output, provider).expect("worker succeeds");
    let envelopes = decode_lines(&output);
    let cancelled = find(&envelopes, "voice.cancelled");

    assert_eq!(cancelled["request_id"], "req-expired");
    assert_eq!(cancelled["payload"]["reason"], "deadline_exceeded");
}

#[test]
fn worker_maps_provider_invalid_payload_to_non_retryable_error() {
    let input =
        br#"{"schema_version":1,"kind":"command","type":"voice.transcribe","request_id":"req-invalid","payload":{"audio_path":"/tmp/input.wav"}}
"#;
    let mut output = Vec::new();

    run_with_provider(&input[..], &mut output, InvalidPayloadProvider).expect("worker succeeds");
    let envelopes = decode_lines(&output);
    let error = find(&envelopes, "voice.error");

    assert_eq!(error["request_id"], "req-invalid");
    assert_eq!(error["payload"]["code"], "invalid_payload");
    assert_eq!(error["payload"]["message"], "audio too long");
    assert_eq!(error["payload"]["retryable"], false);
}

#[test]
fn worker_emits_completed_result_while_stdin_remains_open() {
    let input = SharedInput::new();
    let output = RecordingWriter::new();
    let output_for_worker = output.clone();
    let input_for_worker = input.clone();
    let done = thread::spawn(move || {
        let mut output = output_for_worker;
        run_with_provider(input_for_worker, &mut output, MockProvider)
    });

    wait_for_envelope(&output, "voice.ready");
    input.write_line(
        r#"{"schema_version":1,"kind":"command","type":"voice.transcribe","request_id":"req-one","payload":{"audio_path":"/tmp/input.wav"}}"#,
    );

    let result = wait_for_envelope(&output, "voice.transcribe.result");
    assert_eq!(result["request_id"], "req-one");
    assert_eq!(result["payload"]["text"], "play music");

    input.close();
    done.join()
        .expect("worker thread joins")
        .expect("worker succeeds");
}

fn env_lock() -> &'static Mutex<()> {
    static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
    LOCK.get_or_init(|| Mutex::new(()))
}

fn decode_lines(output: &[u8]) -> Vec<Value> {
    String::from_utf8(output.to_vec())
        .expect("worker output is utf8")
        .lines()
        .map(|line| serde_json::from_str(line).expect("worker line is JSON"))
        .collect()
}

fn find<'a>(envelopes: &'a [Value], message_type: &str) -> &'a Value {
    envelopes
        .iter()
        .find(|envelope| envelope["type"] == message_type)
        .unwrap_or_else(|| panic!("missing envelope {message_type}: {envelopes:#?}"))
}

fn wait_for_envelope(output: &RecordingWriter, message_type: &str) -> Value {
    let deadline = Instant::now() + Duration::from_secs(1);
    let mut observed = Vec::new();
    while Instant::now() < deadline {
        for line in output.drain_lines() {
            let envelope: Value = serde_json::from_str(&line).expect("worker line is JSON");
            if envelope["type"] == message_type {
                return envelope;
            }
            observed.push(envelope);
        }
        thread::sleep(Duration::from_millis(5));
    }
    panic!("timed out waiting for {message_type}; observed: {observed:#?}");
}

#[derive(Clone)]
struct RecordingWriter {
    lines: Arc<Mutex<Vec<String>>>,
}

impl RecordingWriter {
    fn new() -> Self {
        Self {
            lines: Arc::new(Mutex::new(Vec::new())),
        }
    }

    fn drain_lines(&self) -> Vec<String> {
        let mut lines = self.lines.lock().expect("recording writer lock");
        lines.drain(..).collect()
    }
}

impl Write for RecordingWriter {
    fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
        let mut lines = self.lines.lock().expect("recording writer lock");
        for line in String::from_utf8_lossy(buffer).lines() {
            if !line.trim().is_empty() {
                lines.push(line.to_string());
            }
        }
        Ok(buffer.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

#[derive(Clone)]
struct SharedInput {
    state: Arc<SharedInputState>,
}

struct SharedInputState {
    buffer: Mutex<VecDeque<u8>>,
    condvar: Condvar,
    closed: Mutex<bool>,
}

impl SharedInput {
    fn new() -> Self {
        Self {
            state: Arc::new(SharedInputState {
                buffer: Mutex::new(VecDeque::new()),
                condvar: Condvar::new(),
                closed: Mutex::new(false),
            }),
        }
    }

    fn write_line(&self, line: &str) {
        let mut buffer = self.state.buffer.lock().expect("input buffer lock");
        buffer.extend(line.as_bytes());
        buffer.push_back(b'\n');
        self.state.condvar.notify_all();
    }

    fn close(&self) {
        *self.state.closed.lock().expect("input closed lock") = true;
        self.state.condvar.notify_all();
    }
}

impl Read for SharedInput {
    fn read(&mut self, target: &mut [u8]) -> io::Result<usize> {
        let mut buffer = self.state.buffer.lock().expect("input buffer lock");
        loop {
            if !buffer.is_empty() {
                let mut count = 0;
                while count < target.len() {
                    let Some(byte) = buffer.pop_front() else {
                        break;
                    };
                    target[count] = byte;
                    count += 1;
                }
                return Ok(count);
            }
            if *self.state.closed.lock().expect("input closed lock") {
                return Ok(0);
            }
            buffer = self.state.condvar.wait(buffer).expect("input condvar wait");
        }
    }
}

struct EnvGuard<'a> {
    previous: Vec<(&'a str, Option<String>)>,
}

impl<'a> EnvGuard<'a> {
    fn new(keys: &'a [&'a str]) -> Self {
        Self {
            previous: keys
                .iter()
                .map(|key| (*key, std::env::var(key).ok()))
                .collect(),
        }
    }
}

impl Drop for EnvGuard<'_> {
    fn drop(&mut self) {
        for (key, value) in &self.previous {
            if let Some(value) = value {
                std::env::set_var(key, value);
            } else {
                std::env::remove_var(key);
            }
        }
    }
}

#[derive(Clone)]
struct BlockingProvider {
    state: Arc<BlockingState>,
}

struct BlockingState {
    entered: (Mutex<bool>, Condvar),
    released: (Mutex<bool>, Condvar),
}

impl BlockingProvider {
    fn new() -> Self {
        Self {
            state: Arc::new(BlockingState {
                entered: (Mutex::new(false), Condvar::new()),
                released: (Mutex::new(false), Condvar::new()),
            }),
        }
    }

    fn wait_entered(&self) {
        let (lock, condvar) = &self.state.entered;
        let mut entered = lock.lock().expect("entered lock");
        while !*entered {
            entered = condvar.wait(entered).expect("entered condvar");
        }
    }

    fn release(&self) {
        let (lock, condvar) = &self.state.released;
        *lock.lock().expect("release lock") = true;
        condvar.notify_all();
    }

    fn wait_released(&self) {
        let (entered_lock, entered_condvar) = &self.state.entered;
        *entered_lock.lock().expect("entered lock") = true;
        entered_condvar.notify_all();
        let (release_lock, release_condvar) = &self.state.released;
        let mut released = release_lock.lock().expect("release lock");
        while !*released {
            released = release_condvar.wait(released).expect("release condvar");
        }
    }
}

impl SpeechProvider for BlockingProvider {
    fn health(&self, _context: &SpeechRequestContext) -> Result<HealthResult> {
        Ok(HealthResult {
            healthy: true,
            provider: "blocking".to_string(),
            message: None,
        })
    }

    fn transcribe(
        &self,
        _context: &SpeechRequestContext,
        _request: TranscribeRequest,
    ) -> Result<TranscribeResult> {
        self.wait_released();
        Ok(TranscribeResult {
            text: "done".to_string(),
            confidence: 1.0,
            is_final: true,
            provider_latency_ms: None,
            audio_duration_ms: None,
        })
    }

    fn speak(
        &self,
        _context: &SpeechRequestContext,
        _request: SpeakRequest,
    ) -> Result<SpeakResult> {
        self.wait_released();
        Ok(SpeakResult {
            audio_path: "/tmp/out.wav".to_string(),
            format: "wav".to_string(),
            sample_rate_hz: 16_000,
            duration_ms: None,
            provider_latency_ms: None,
        })
    }

    fn ask(&self, _context: &SpeechRequestContext, _request: AskRequest) -> Result<AskResult> {
        self.wait_released();
        Ok(AskResult {
            answer: "done".to_string(),
            model: "blocking".to_string(),
            provider_latency_ms: None,
        })
    }
}

struct DeadlineAwareProvider;

impl SpeechProvider for DeadlineAwareProvider {
    fn health(&self, _context: &SpeechRequestContext) -> Result<HealthResult> {
        unreachable!("health is not used")
    }

    fn transcribe(
        &self,
        context: &SpeechRequestContext,
        _request: TranscribeRequest,
    ) -> Result<TranscribeResult> {
        let started = Instant::now();
        while !context.is_cancelled() && started.elapsed() < Duration::from_millis(200) {
            thread::sleep(Duration::from_millis(2));
        }
        anyhow::bail!(context.cancellation_reason());
    }

    fn speak(
        &self,
        _context: &SpeechRequestContext,
        _request: SpeakRequest,
    ) -> Result<SpeakResult> {
        unreachable!("speak is not used")
    }

    fn ask(&self, _context: &SpeechRequestContext, _request: AskRequest) -> Result<AskResult> {
        unreachable!("ask is not used")
    }
}

struct InvalidPayloadProvider;

impl SpeechProvider for InvalidPayloadProvider {
    fn health(&self, _context: &SpeechRequestContext) -> Result<HealthResult> {
        Ok(HealthResult {
            healthy: true,
            provider: "invalid-payload".to_string(),
            message: None,
        })
    }

    fn transcribe(
        &self,
        _context: &SpeechRequestContext,
        _request: TranscribeRequest,
    ) -> Result<TranscribeResult> {
        Err(invalid_payload("audio too long"))
    }

    fn speak(
        &self,
        _context: &SpeechRequestContext,
        _request: SpeakRequest,
    ) -> Result<SpeakResult> {
        Err(invalid_payload("text too long"))
    }

    fn ask(&self, _context: &SpeechRequestContext, _request: AskRequest) -> Result<AskResult> {
        Err(invalid_payload("question required"))
    }
}
