use std::collections::HashMap;
use std::fs;
use std::io::{Read, Write};
use std::net::TcpListener;
use std::sync::mpsc;
use std::thread;
use std::time::Duration;

use yoyopod_speech_host::provider::{
    new_openai_provider_from_env, wav_duration_seconds, AskRequest, AskTurn, OpenAiProvider,
    SpeakRequest, SpeechProvider, SpeechRequestContext, TranscribeRequest,
};

#[test]
fn openai_provider_transcribe_builds_multipart_request() {
    let audio_path = write_test_wav(b"RIFF-test-audio-WAVE");
    let server = TestServer::spawn(http_response(
        "application/json",
        r#"{"text":"play music"}"#,
    ));

    let result = OpenAiProvider {
        base_url: server.url(),
        api_key: "test-key".to_string(),
        stt_model: "default-stt".to_string(),
        ..OpenAiProvider::default()
    }
    .transcribe(
        &SpeechRequestContext::default(),
        TranscribeRequest {
            audio_path: audio_path.to_string_lossy().to_string(),
            language: "en".to_string(),
            model: "custom-stt".to_string(),
            prompt: "Transcribe YoYoPod commands in English Latin letters.".to_string(),
            ..TranscribeRequest::default()
        },
    )
    .expect("transcribe succeeds");

    let request = server.request();
    assert_eq!(request.path, "/v1/audio/transcriptions");
    assert_eq!(request.header("authorization"), "Bearer test-key");
    assert!(request
        .header("content-type")
        .starts_with("multipart/form-data; boundary="));
    let body = String::from_utf8_lossy(&request.body);
    assert!(body.contains("name=\"model\"\r\n\r\ncustom-stt"));
    assert!(body.contains("name=\"language\"\r\n\r\nen"));
    assert!(body
        .contains("name=\"prompt\"\r\n\r\nTranscribe YoYoPod commands in English Latin letters."));
    assert!(body.contains("name=\"response_format\"\r\n\r\njson"));
    assert!(body.contains("name=\"file\""));
    assert!(body.contains("filename=\"input.wav\""));
    assert!(body.contains("RIFF-test-audio-WAVE"));
    assert_eq!(result.text, "play music");
    assert_eq!(result.confidence, 1.0);
    assert!(result.is_final);
}

#[test]
fn openai_provider_speak_posts_json_and_writes_wav() {
    let server = TestServer::spawn(http_response("audio/wav", "RIFF-test-output-WAVE"));

    let result = OpenAiProvider {
        base_url: server.url(),
        api_key: "test-key".to_string(),
        tts_model: "default-tts".to_string(),
        tts_voice: "alloy".to_string(),
        ..OpenAiProvider::default()
    }
    .speak(
        &SpeechRequestContext::default(),
        SpeakRequest {
            text: "Playing music".to_string(),
            model: "custom-tts".to_string(),
            voice: "verse".to_string(),
            instructions: "Speak warmly.".to_string(),
            ..SpeakRequest::default()
        },
    )
    .expect("speak succeeds");

    let request = server.request();
    assert_eq!(request.path, "/v1/audio/speech");
    assert_eq!(request.header("authorization"), "Bearer test-key");
    assert_eq!(request.header("content-type"), "application/json");
    let payload: serde_json::Value =
        serde_json::from_slice(&request.body).expect("request body is JSON");
    assert_eq!(payload["model"], "custom-tts");
    assert_eq!(payload["input"], "Playing music");
    assert_eq!(payload["voice"], "verse");
    assert_eq!(payload["instructions"], "Speak warmly.");
    assert_eq!(payload["response_format"], "wav");
    assert_eq!(result.format, "wav");
    assert_eq!(result.sample_rate_hz, 16_000);
    assert_eq!(
        fs::read_to_string(&result.audio_path).expect("read generated wav"),
        "RIFF-test-output-WAVE"
    );
    let _ = fs::remove_file(result.audio_path);
}

#[test]
fn openai_provider_speak_omits_empty_instructions() {
    let server = TestServer::spawn(http_response("audio/wav", "RIFF-test-output-WAVE"));

    let result = OpenAiProvider {
        base_url: server.url(),
        api_key: "test-key".to_string(),
        ..OpenAiProvider::default()
    }
    .speak(
        &SpeechRequestContext::default(),
        SpeakRequest {
            text: "Playing music".to_string(),
            ..SpeakRequest::default()
        },
    )
    .expect("speak succeeds");

    let request = server.request();
    let payload: serde_json::Value =
        serde_json::from_slice(&request.body).expect("request body is JSON");
    assert!(payload.get("instructions").is_none());
    let _ = fs::remove_file(result.audio_path);
}

#[test]
fn openai_provider_ask_posts_responses_request_and_parses_output_text() {
    let server = TestServer::spawn(http_response(
        "application/json",
        r#"{"output_text":"  A small answer.  "}"#,
    ));

    let result = OpenAiProvider {
        base_url: server.url(),
        api_key: "test-key".to_string(),
        ask_model: "default-ask".to_string(),
        ..OpenAiProvider::default()
    }
    .ask(
        &SpeechRequestContext::default(),
        AskRequest {
            question: "What now?".to_string(),
            model: "custom-ask".to_string(),
            instructions: "Answer gently.".to_string(),
            history: vec![
                AskTurn {
                    role: "user".to_string(),
                    text: "Earlier question".to_string(),
                },
                AskTurn {
                    role: "assistant".to_string(),
                    text: "Earlier answer".to_string(),
                },
                AskTurn {
                    role: "tool".to_string(),
                    text: "ignored role".to_string(),
                },
                AskTurn {
                    role: "user".to_string(),
                    text: "   ".to_string(),
                },
            ],
            ..AskRequest::default()
        },
    )
    .expect("ask succeeds");

    let request = server.request();
    assert_eq!(request.path, "/v1/responses");
    assert_eq!(request.header("authorization"), "Bearer test-key");
    assert_eq!(request.header("content-type"), "application/json");
    let payload: serde_json::Value =
        serde_json::from_slice(&request.body).expect("request body is JSON");
    assert_eq!(payload["model"], "custom-ask");
    assert_eq!(payload["instructions"], "Answer gently.");
    assert_eq!(payload["input"][0]["role"], "user");
    assert_eq!(payload["input"][0]["content"], "Earlier question");
    assert_eq!(payload["input"][1]["role"], "assistant");
    assert_eq!(payload["input"][1]["content"], "Earlier answer");
    assert_eq!(payload["input"][2]["role"], "user");
    assert_eq!(payload["input"][2]["content"], "What now?");
    assert_eq!(payload["input"].as_array().expect("input array").len(), 3);
    assert_eq!(result.answer, "A small answer.");
    assert_eq!(result.model, "custom-ask");
}

#[test]
fn openai_provider_ask_parses_structured_output_fallback_and_truncates() {
    let server = TestServer::spawn(http_response(
        "application/json",
        r#"{"output":[{"content":[{"type":"summary_text","text":"ignored"},{"type":"output_text","text":"Structured answer"}]}]}"#,
    ));

    let result = OpenAiProvider {
        base_url: server.url(),
        api_key: "test-key".to_string(),
        ask_model: "default-ask".to_string(),
        ..OpenAiProvider::default()
    }
    .ask(
        &SpeechRequestContext::default(),
        AskRequest {
            question: "What now?".to_string(),
            max_output_chars: 10,
            ..AskRequest::default()
        },
    )
    .expect("ask succeeds");

    assert_eq!(result.answer, "Structured");
    assert_eq!(result.model, "default-ask");
}

#[test]
fn openai_provider_error_body_is_limited() {
    let long_body = format!("{}tail-marker", "x".repeat(5000));
    let response = format!(
        "HTTP/1.1 400 Bad Request\r\nContent-Type: text/plain\r\nContent-Length: {}\r\n\r\n{}",
        long_body.len(),
        long_body
    );
    let server = TestServer::spawn(response);

    let error = OpenAiProvider {
        base_url: server.url(),
        api_key: "test-key".to_string(),
        ..OpenAiProvider::default()
    }
    .ask(
        &SpeechRequestContext::default(),
        AskRequest {
            question: "What now?".to_string(),
            ..AskRequest::default()
        },
    )
    .expect_err("ask fails");

    let message = error.to_string();
    assert!(message.contains("status=400"));
    assert!(!message.contains("tail-marker"));
}

#[test]
fn openai_provider_in_flight_request_returns_when_context_is_cancelled() {
    let server = TestServer::spawn_without_response();
    let context = SpeechRequestContext::default();
    let context_for_worker = context.clone();
    let provider = OpenAiProvider {
        base_url: server.url(),
        api_key: "test-key".to_string(),
        ..OpenAiProvider::default()
    };
    let (sender, receiver) = mpsc::channel();

    thread::spawn(move || {
        let result = provider.ask(
            &context_for_worker,
            AskRequest {
                question: "What now?".to_string(),
                ..AskRequest::default()
            },
        );
        sender.send(result).expect("send provider result");
    });

    let request = server.request();
    assert_eq!(request.path, "/v1/responses");
    context.cancel();
    let result = receiver
        .recv_timeout(Duration::from_secs(1))
        .expect("cancelled context should unblock in-flight request");
    let error = result.expect_err("cancelled request fails");
    assert!(error.to_string().contains("cancelled"));
}

#[test]
fn openai_provider_rejects_over_limit_wav_before_upload() {
    let audio_path = write_test_wav(&make_test_wav(16_000, 1, 16, 2 * 16_000 * 2));
    let server = TestServer::spawn(
        "HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\n\r\n".to_string(),
    );

    let error = OpenAiProvider {
        base_url: server.url(),
        api_key: "test-key".to_string(),
        ..OpenAiProvider::default()
    }
    .transcribe(
        &SpeechRequestContext::default(),
        TranscribeRequest {
            audio_path: audio_path.to_string_lossy().to_string(),
            max_audio_seconds: 1.0,
            ..TranscribeRequest::default()
        },
    )
    .expect_err("over-limit wav should fail before upload");

    assert!(error.to_string().contains("exceeds max_audio_seconds"));
    assert!(server.try_request().is_none());
}

#[test]
fn openai_provider_returns_missing_api_key_errors() {
    let provider = OpenAiProvider {
        base_url: "http://127.0.0.1:1".to_string(),
        ..OpenAiProvider::default()
    };

    assert!(provider
        .health(&SpeechRequestContext::default())
        .expect_err("health fails")
        .to_string()
        .contains("OPENAI_API_KEY"));
    assert!(provider
        .transcribe(
            &SpeechRequestContext::default(),
            TranscribeRequest::default()
        )
        .expect_err("transcribe fails")
        .to_string()
        .contains("OPENAI_API_KEY"));
    assert!(provider
        .speak(&SpeechRequestContext::default(), SpeakRequest::default())
        .expect_err("speak fails")
        .to_string()
        .contains("OPENAI_API_KEY"));
    assert!(provider
        .ask(
            &SpeechRequestContext::default(),
            AskRequest {
                question: "hello".to_string(),
                ..AskRequest::default()
            }
        )
        .expect_err("ask fails")
        .to_string()
        .contains("OPENAI_API_KEY"));
}

#[test]
fn new_openai_provider_from_env_uses_defaults_and_overrides() {
    let _guard = EnvGuard::new(&[
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
        "YOYOPOD_CLOUD_STT_MODEL",
        "YOYOPOD_CLOUD_TTS_MODEL",
        "YOYOPOD_CLOUD_TTS_VOICE",
        "YOYOPOD_CLOUD_ASK_MODEL",
    ]);
    for key in _guard.keys {
        std::env::remove_var(key);
    }

    let defaults = new_openai_provider_from_env();
    assert_eq!(defaults.base_url, "https://api.openai.com");
    assert_eq!(defaults.stt_model, "gpt-4o-mini-transcribe");
    assert_eq!(defaults.tts_model, "gpt-4o-mini-tts");
    assert_eq!(defaults.tts_voice, "alloy");
    assert_eq!(defaults.ask_model, "gpt-4.1-mini");

    std::env::set_var("OPENAI_BASE_URL", "https://openai.test");
    std::env::set_var("OPENAI_API_KEY", "env-key");
    std::env::set_var("YOYOPOD_CLOUD_STT_MODEL", "env-stt");
    std::env::set_var("YOYOPOD_CLOUD_TTS_MODEL", "env-tts");
    std::env::set_var("YOYOPOD_CLOUD_TTS_VOICE", "verse");
    std::env::set_var("YOYOPOD_CLOUD_ASK_MODEL", "env-ask");

    let overrides = new_openai_provider_from_env();
    assert_eq!(overrides.base_url, "https://openai.test");
    assert_eq!(overrides.api_key, "env-key");
    assert_eq!(overrides.stt_model, "env-stt");
    assert_eq!(overrides.tts_model, "env-tts");
    assert_eq!(overrides.tts_voice, "verse");
    assert_eq!(overrides.ask_model, "env-ask");
}

#[test]
fn wav_duration_uses_actual_file_size_for_streaming_data_chunk() {
    let audio_path = write_test_wav(&make_streaming_data_size_wav(24_000, 1, 16, 24_000 * 2));

    let duration = wav_duration_seconds(&audio_path).expect("streaming wav duration");

    assert_eq!(duration, Some(1.0));
}

struct TestServer {
    url: String,
    receiver: mpsc::Receiver<CapturedRequest>,
}

impl TestServer {
    fn spawn(response: String) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind test server");
        let url = format!("http://{}", listener.local_addr().expect("local addr"));
        let (sender, receiver) = mpsc::channel();
        thread::spawn(move || {
            if let Ok((mut stream, _addr)) = listener.accept() {
                let request = read_request(&mut stream);
                let _ = sender.send(request);
                let _ = stream.write_all(response.as_bytes());
            }
        });
        Self { url, receiver }
    }

    fn spawn_without_response() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind test server");
        let url = format!("http://{}", listener.local_addr().expect("local addr"));
        let (sender, receiver) = mpsc::channel();
        thread::spawn(move || {
            if let Ok((mut stream, _addr)) = listener.accept() {
                let request = read_request(&mut stream);
                let _ = sender.send(request);
                thread::sleep(Duration::from_secs(5));
            }
        });
        Self { url, receiver }
    }

    fn url(&self) -> String {
        self.url.clone()
    }

    fn request(&self) -> CapturedRequest {
        self.receiver.recv().expect("captured request")
    }

    fn try_request(&self) -> Option<CapturedRequest> {
        self.receiver
            .recv_timeout(std::time::Duration::from_millis(100))
            .ok()
    }
}

fn http_response(content_type: &str, body: &str) -> String {
    format!(
        "HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\n\r\n{body}",
        body.len()
    )
}

struct CapturedRequest {
    path: String,
    headers: HashMap<String, String>,
    body: Vec<u8>,
}

impl CapturedRequest {
    fn header(&self, name: &str) -> &str {
        self.headers
            .get(&name.to_ascii_lowercase())
            .map(String::as_str)
            .unwrap_or("")
    }
}

fn read_request(stream: &mut impl Read) -> CapturedRequest {
    let mut buffer = Vec::new();
    let mut chunk = [0u8; 4096];
    loop {
        let read = stream.read(&mut chunk).expect("read request");
        assert!(read > 0, "connection closed before headers");
        buffer.extend_from_slice(&chunk[..read]);
        if find_subslice(&buffer, b"\r\n\r\n").is_some() {
            break;
        }
    }
    let header_end = find_subslice(&buffer, b"\r\n\r\n").expect("header end") + 4;
    let head = String::from_utf8_lossy(&buffer[..header_end]);
    let mut lines = head.lines();
    let request_line = lines.next().expect("request line");
    let path = request_line
        .split_whitespace()
        .nth(1)
        .expect("request path")
        .to_string();
    let headers: HashMap<String, String> = lines
        .filter_map(|line| line.split_once(':'))
        .map(|(key, value)| (key.to_ascii_lowercase(), value.trim().to_string()))
        .collect();
    let content_length = headers
        .get("content-length")
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(0);
    while buffer.len() < header_end + content_length {
        let read = stream.read(&mut chunk).expect("read request body");
        assert!(read > 0, "connection closed before body");
        buffer.extend_from_slice(&chunk[..read]);
    }
    CapturedRequest {
        path,
        headers,
        body: buffer[header_end..header_end + content_length].to_vec(),
    }
}

fn find_subslice(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack
        .windows(needle.len())
        .position(|window| window == needle)
}

fn write_test_wav(content: &[u8]) -> std::path::PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "yoyopod-speech-openai-test-{}-{}",
        std::process::id(),
        unique_id()
    ));
    fs::create_dir_all(&dir).expect("create temp dir");
    let path = dir.join("input.wav");
    fs::write(&path, content).expect("write wav");
    path
}

fn make_test_wav(
    sample_rate_hz: u32,
    channels: u16,
    bits_per_sample: u16,
    data_bytes: usize,
) -> Vec<u8> {
    let block_align = channels * bits_per_sample / 8;
    let byte_rate = sample_rate_hz * u32::from(block_align);
    let riff_size = 36 + data_bytes as u32;
    let mut wav = vec![0; 44 + data_bytes];
    wav[0..4].copy_from_slice(b"RIFF");
    put_u32(&mut wav[4..8], riff_size);
    wav[8..12].copy_from_slice(b"WAVE");
    wav[12..16].copy_from_slice(b"fmt ");
    put_u32(&mut wav[16..20], 16);
    put_u16(&mut wav[20..22], 1);
    put_u16(&mut wav[22..24], channels);
    put_u32(&mut wav[24..28], sample_rate_hz);
    put_u32(&mut wav[28..32], byte_rate);
    put_u16(&mut wav[32..34], block_align);
    put_u16(&mut wav[34..36], bits_per_sample);
    wav[36..40].copy_from_slice(b"data");
    put_u32(&mut wav[40..44], data_bytes as u32);
    wav
}

fn make_streaming_data_size_wav(
    sample_rate_hz: u32,
    channels: u16,
    bits_per_sample: u16,
    data_bytes: usize,
) -> Vec<u8> {
    let mut wav = make_test_wav(sample_rate_hz, channels, bits_per_sample, data_bytes);
    put_u32(&mut wav[4..8], u32::MAX);
    put_u32(&mut wav[40..44], u32::MAX);
    wav
}

fn put_u16(target: &mut [u8], value: u16) {
    target.copy_from_slice(&value.to_le_bytes());
}

fn put_u32(target: &mut [u8], value: u32) {
    target.copy_from_slice(&value.to_le_bytes());
}

fn unique_id() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("clock after UNIX_EPOCH")
        .as_nanos()
}

struct EnvGuard<'a> {
    keys: &'a [&'a str],
    previous: Vec<(&'a str, Option<String>)>,
}

impl<'a> EnvGuard<'a> {
    fn new(keys: &'a [&'a str]) -> Self {
        Self {
            keys,
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
