use std::env;
use std::fs;
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    mpsc::{self, RecvTimeoutError},
    Arc,
};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use anyhow::{anyhow, bail, Result};
use serde::{Deserialize, Serialize};
use serde_json::json;
use thiserror::Error;

const DEFAULT_OPENAI_BASE_URL: &str = "https://api.openai.com";
const DEFAULT_OPENAI_ASK_MODEL: &str = "gpt-4.1-mini";
const DEFAULT_OPENAI_STT_MODEL: &str = "gpt-4o-mini-transcribe";
const DEFAULT_OPENAI_TTS_MODEL: &str = "gpt-4o-mini-tts";
const DEFAULT_OPENAI_TTS_VOICE: &str = "alloy";
const DEFAULT_OPENAI_HTTP_TIMEOUT: Duration = Duration::from_secs(30);
const MAX_ERROR_BODY_BYTES: u64 = 4096;
const DEFAULT_STT_SAMPLE_RATE: u32 = 16_000;
const DEFAULT_STT_CHANNELS: u32 = 1;
const DEFAULT_TTS_SAMPLE_RATE: u32 = 16_000;
const STT_BYTES_PER_SAMPLE: u32 = 2;
const AUDIO_SIZE_ALLOWANCE: u64 = 4096;
const WAV_HEADER_PROBE_BYTES: u64 = 1024 * 1024;
const UNKNOWN_WAV_CHUNK_SIZE: u32 = u32::MAX;

#[derive(Debug, Clone)]
pub struct SpeechRequestContext {
    cancelled: Arc<AtomicBool>,
    deadline: Option<Instant>,
}

impl SpeechRequestContext {
    pub fn new(deadline_ms: u64) -> Self {
        let deadline = if deadline_ms > 0 {
            Some(Instant::now() + std::time::Duration::from_millis(deadline_ms))
        } else {
            None
        };
        Self {
            cancelled: Arc::new(AtomicBool::new(false)),
            deadline,
        }
    }

    pub fn cancel(&self) {
        self.cancelled.store(true, Ordering::SeqCst);
    }

    pub fn is_cancelled(&self) -> bool {
        self.cancelled.load(Ordering::SeqCst)
            || self
                .deadline
                .is_some_and(|deadline| Instant::now() >= deadline)
    }

    pub fn cancellation_reason(&self) -> &'static str {
        if self
            .deadline
            .is_some_and(|deadline| Instant::now() >= deadline)
        {
            "deadline_exceeded"
        } else {
            "cancelled"
        }
    }

    pub fn remaining_until_deadline(&self) -> Option<Duration> {
        self.deadline
            .map(|deadline| deadline.saturating_duration_since(Instant::now()))
    }
}

impl Default for SpeechRequestContext {
    fn default() -> Self {
        Self::new(0)
    }
}

pub trait SpeechProvider: Send + Sync {
    fn health(&self, context: &SpeechRequestContext) -> Result<HealthResult>;
    fn transcribe(
        &self,
        context: &SpeechRequestContext,
        request: TranscribeRequest,
    ) -> Result<TranscribeResult>;
    fn speak(&self, context: &SpeechRequestContext, request: SpeakRequest) -> Result<SpeakResult>;
    fn ask(&self, context: &SpeechRequestContext, request: AskRequest) -> Result<AskResult>;
}

#[derive(Debug, Error)]
#[error("{message}")]
pub struct InvalidPayloadError {
    message: String,
}

pub fn invalid_payload(message: impl Into<String>) -> anyhow::Error {
    InvalidPayloadError {
        message: message.into(),
    }
    .into()
}

pub fn is_invalid_payload(error: &anyhow::Error) -> bool {
    error.downcast_ref::<InvalidPayloadError>().is_some()
}

impl<T> SpeechProvider for Box<T>
where
    T: SpeechProvider + ?Sized,
{
    fn health(&self, context: &SpeechRequestContext) -> Result<HealthResult> {
        (**self).health(context)
    }

    fn transcribe(
        &self,
        context: &SpeechRequestContext,
        request: TranscribeRequest,
    ) -> Result<TranscribeResult> {
        (**self).transcribe(context, request)
    }

    fn speak(&self, context: &SpeechRequestContext, request: SpeakRequest) -> Result<SpeakResult> {
        (**self).speak(context, request)
    }

    fn ask(&self, context: &SpeechRequestContext, request: AskRequest) -> Result<AskResult> {
        (**self).ask(context, request)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct HealthResult {
    pub healthy: bool,
    pub provider: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct TranscribeRequest {
    #[serde(default)]
    pub audio_path: String,
    #[serde(default)]
    pub format: String,
    #[serde(default)]
    pub sample_rate_hz: u32,
    #[serde(default)]
    pub channels: u32,
    #[serde(default)]
    pub language: String,
    #[serde(default)]
    pub model: String,
    #[serde(default)]
    pub prompt: String,
    #[serde(default)]
    pub max_audio_seconds: f64,
    #[serde(default)]
    pub delete_input_on_success: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct TranscribeResult {
    pub text: String,
    pub confidence: f64,
    pub is_final: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub provider_latency_ms: Option<u128>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub audio_duration_ms: Option<u128>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct SpeakRequest {
    #[serde(default)]
    pub text: String,
    #[serde(default)]
    pub voice: String,
    #[serde(default)]
    pub model: String,
    #[serde(default)]
    pub instructions: String,
    #[serde(default)]
    pub format: String,
    #[serde(default)]
    pub sample_rate_hz: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct SpeakResult {
    pub audio_path: String,
    pub format: String,
    pub sample_rate_hz: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub duration_ms: Option<u128>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub provider_latency_ms: Option<u128>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct AskTurn {
    pub role: String,
    pub text: String,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct AskRequest {
    #[serde(default)]
    pub question: String,
    #[serde(default)]
    pub history: Vec<AskTurn>,
    #[serde(default)]
    pub model: String,
    #[serde(default)]
    pub instructions: String,
    #[serde(default)]
    pub max_output_chars: usize,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct AskResult {
    pub answer: String,
    pub model: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub provider_latency_ms: Option<u128>,
}

#[derive(Debug, Clone, Copy, Default)]
pub struct MockProvider;

impl SpeechProvider for MockProvider {
    fn health(&self, context: &SpeechRequestContext) -> Result<HealthResult> {
        if context.is_cancelled() {
            bail!(context.cancellation_reason());
        }
        Ok(HealthResult {
            healthy: true,
            provider: "mock".to_string(),
            message: None,
        })
    }

    fn transcribe(
        &self,
        context: &SpeechRequestContext,
        _request: TranscribeRequest,
    ) -> Result<TranscribeResult> {
        let started_at = Instant::now();
        if context.is_cancelled() {
            bail!(context.cancellation_reason());
        }
        Ok(TranscribeResult {
            text: env_or_default("YOYOPOD_MOCK_TRANSCRIPT", "play music"),
            confidence: 1.0,
            is_final: true,
            provider_latency_ms: Some(started_at.elapsed().as_millis()),
            audio_duration_ms: None,
        })
    }

    fn speak(&self, context: &SpeechRequestContext, request: SpeakRequest) -> Result<SpeakResult> {
        let started_at = Instant::now();
        if context.is_cancelled() {
            bail!(context.cancellation_reason());
        }
        let output_path = mock_tts_path()?;
        fs::write(&output_path, mock_wav())?;
        Ok(SpeakResult {
            audio_path: output_path.to_string_lossy().to_string(),
            format: "wav".to_string(),
            sample_rate_hz: if request.sample_rate_hz == 0 {
                16_000
            } else {
                request.sample_rate_hz
            },
            duration_ms: Some(100),
            provider_latency_ms: Some(started_at.elapsed().as_millis()),
        })
    }

    fn ask(&self, context: &SpeechRequestContext, request: AskRequest) -> Result<AskResult> {
        let started_at = Instant::now();
        if context.is_cancelled() {
            bail!(context.cancellation_reason());
        }
        let model = if request.model.trim().is_empty() {
            "mock".to_string()
        } else {
            request.model
        };
        Ok(AskResult {
            answer: env_or_default(
                "YOYOPOD_MOCK_ASK_ANSWER",
                "I can answer that in a small, friendly way.",
            ),
            model,
            provider_latency_ms: Some(started_at.elapsed().as_millis()),
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OpenAiProvider {
    pub base_url: String,
    pub api_key: String,
    pub ask_model: String,
    pub stt_model: String,
    pub tts_model: String,
    pub tts_voice: String,
}

impl Default for OpenAiProvider {
    fn default() -> Self {
        Self {
            base_url: DEFAULT_OPENAI_BASE_URL.to_string(),
            api_key: String::new(),
            ask_model: DEFAULT_OPENAI_ASK_MODEL.to_string(),
            stt_model: DEFAULT_OPENAI_STT_MODEL.to_string(),
            tts_model: DEFAULT_OPENAI_TTS_MODEL.to_string(),
            tts_voice: DEFAULT_OPENAI_TTS_VOICE.to_string(),
        }
    }
}

pub fn new_openai_provider_from_env() -> OpenAiProvider {
    OpenAiProvider {
        base_url: env_or_default("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
        api_key: env::var("OPENAI_API_KEY").unwrap_or_default(),
        ask_model: env_or_default("YOYOPOD_CLOUD_ASK_MODEL", DEFAULT_OPENAI_ASK_MODEL),
        stt_model: env_or_default("YOYOPOD_CLOUD_STT_MODEL", DEFAULT_OPENAI_STT_MODEL),
        tts_model: env_or_default("YOYOPOD_CLOUD_TTS_MODEL", DEFAULT_OPENAI_TTS_MODEL),
        tts_voice: env_or_default("YOYOPOD_CLOUD_TTS_VOICE", DEFAULT_OPENAI_TTS_VOICE),
    }
}

impl SpeechProvider for OpenAiProvider {
    fn health(&self, context: &SpeechRequestContext) -> Result<HealthResult> {
        self.require_api_key()?;
        if context.is_cancelled() {
            bail!(context.cancellation_reason());
        }
        Ok(HealthResult {
            healthy: true,
            provider: "openai".to_string(),
            message: None,
        })
    }

    fn transcribe(
        &self,
        context: &SpeechRequestContext,
        request: TranscribeRequest,
    ) -> Result<TranscribeResult> {
        let started_at = Instant::now();
        self.require_api_key()?;
        if context.is_cancelled() {
            bail!(context.cancellation_reason());
        }
        validate_transcription_audio(&request)?;
        let audio = fs::read(&request.audio_path)?;
        let model = if request.model.is_empty() {
            self.stt_model.as_str()
        } else {
            request.model.as_str()
        };
        let boundary = format!("yoyopod-speech-{}", unique_id()?);
        let mut body = Vec::new();
        multipart_text(&mut body, &boundary, "model", model)?;
        if !request.language.is_empty() {
            multipart_text(&mut body, &boundary, "language", &request.language)?;
        }
        if !request.prompt.trim().is_empty() {
            multipart_text(&mut body, &boundary, "prompt", &request.prompt)?;
        }
        multipart_text(&mut body, &boundary, "response_format", "json")?;
        multipart_file(
            &mut body,
            &boundary,
            "file",
            Path::new(&request.audio_path)
                .file_name()
                .and_then(|value| value.to_str())
                .unwrap_or("audio.wav"),
            &audio,
        )?;
        write!(body, "--{boundary}--\r\n")?;

        let url = self.url_for("/v1/audio/transcriptions");
        let api_key = self.api_key.clone();
        let timeout = request_timeout(context);
        let response_body = run_abortable(context, move || {
            ureq::post(&url)
                .timeout(timeout)
                .set("Authorization", &format!("Bearer {api_key}"))
                .set(
                    "Content-Type",
                    &format!("multipart/form-data; boundary={boundary}"),
                )
                .send_bytes(&body)
                .map_err(|error| http_error("transcription", error))?
                .into_string()
                .map_err(Into::into)
        })?;
        let decoded: OpenAiTranscriptionResponse = serde_json::from_str(&response_body)?;
        Ok(TranscribeResult {
            text: decoded.text,
            confidence: 1.0,
            is_final: true,
            provider_latency_ms: Some(started_at.elapsed().as_millis()),
            audio_duration_ms: None,
        })
    }

    fn speak(&self, context: &SpeechRequestContext, request: SpeakRequest) -> Result<SpeakResult> {
        let started_at = Instant::now();
        self.require_api_key()?;
        if context.is_cancelled() {
            bail!(context.cancellation_reason());
        }
        let model = if request.model.is_empty() {
            self.tts_model.as_str()
        } else {
            request.model.as_str()
        };
        let voice = if request.voice.is_empty() {
            self.tts_voice.as_str()
        } else {
            request.voice.as_str()
        };
        let mut payload = json!({
            "model": model,
            "input": request.text,
            "voice": voice,
            "response_format": "wav",
        });
        if !request.instructions.is_empty() {
            payload["instructions"] = json!(request.instructions);
        }
        let url = self.url_for("/v1/audio/speech");
        let api_key = self.api_key.clone();
        let encoded_payload = serde_json::to_string(&payload)?;
        let timeout = request_timeout(context);
        let response_body = run_abortable(context, move || {
            let response = ureq::post(&url)
                .timeout(timeout)
                .set("Authorization", &format!("Bearer {api_key}"))
                .set("Content-Type", "application/json")
                .send_bytes(encoded_payload.as_bytes())
                .map_err(|error| http_error("speech", error))?;
            let mut body = Vec::new();
            response.into_reader().read_to_end(&mut body)?;
            Ok(body)
        })?;
        let output_path = temp_wav_path("yoyopod-cloud-tts")?;
        let mut output = fs::File::create(&output_path)?;
        output.write_all(&response_body)?;
        drop(output);
        normalize_streaming_wav_sizes(&output_path)?;
        Ok(SpeakResult {
            audio_path: output_path.to_string_lossy().to_string(),
            format: "wav".to_string(),
            sample_rate_hz: if request.sample_rate_hz == 0 {
                DEFAULT_TTS_SAMPLE_RATE
            } else {
                request.sample_rate_hz
            },
            duration_ms: None,
            provider_latency_ms: Some(started_at.elapsed().as_millis()),
        })
    }

    fn ask(&self, context: &SpeechRequestContext, request: AskRequest) -> Result<AskResult> {
        let started_at = Instant::now();
        self.require_api_key()?;
        if context.is_cancelled() {
            bail!(context.cancellation_reason());
        }
        let question = request.question.trim();
        if question.is_empty() {
            return Err(invalid_payload("question is required"));
        }
        let model = if request.model.is_empty() {
            if self.ask_model.is_empty() {
                DEFAULT_OPENAI_ASK_MODEL.to_string()
            } else {
                self.ask_model.clone()
            }
        } else {
            request.model.clone()
        };
        let payload = json!({
            "model": model,
            "instructions": request.instructions.trim(),
            "input": openai_response_input(&request.history, question),
        });
        let url = self.url_for("/v1/responses");
        let api_key = self.api_key.clone();
        let encoded_payload = serde_json::to_string(&payload)?;
        let timeout = request_timeout(context);
        let response_body = run_abortable(context, move || {
            ureq::post(&url)
                .timeout(timeout)
                .set("Authorization", &format!("Bearer {api_key}"))
                .set("Content-Type", "application/json")
                .send_bytes(encoded_payload.as_bytes())
                .map_err(|error| http_error("response", error))?
                .into_string()
                .map_err(Into::into)
        })?;
        let decoded: OpenAiResponse = serde_json::from_str(&response_body)?;
        let mut answer = decoded.answer_text().trim().to_string();
        if request.max_output_chars > 0 {
            answer = truncate_chars(&answer, request.max_output_chars)
                .trim()
                .to_string();
        }
        if answer.is_empty() {
            bail!("openai response returned empty answer");
        }
        Ok(AskResult {
            answer,
            model,
            provider_latency_ms: Some(started_at.elapsed().as_millis()),
        })
    }
}

impl OpenAiProvider {
    fn require_api_key(&self) -> Result<()> {
        if self.api_key.is_empty() {
            bail!("OPENAI_API_KEY is not set");
        }
        Ok(())
    }

    fn url_for(&self, path: &str) -> String {
        format!("{}{}", self.base_url.trim_end_matches('/'), path)
    }
}

fn env_or_default(key: &str, default_value: &str) -> String {
    env::var(key)
        .ok()
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| default_value.to_string())
}

fn mock_tts_path() -> Result<PathBuf> {
    temp_wav_path("yoyopod-mock-tts")
}

fn temp_wav_path(prefix: &str) -> Result<PathBuf> {
    Ok(env::temp_dir().join(format!(
        "{}-{}-{}.wav",
        prefix,
        std::process::id(),
        unique_id()?
    )))
}

fn unique_id() -> Result<u128> {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| anyhow!("system clock before UNIX_EPOCH: {error}"))?
        .as_nanos();
    Ok(nanos)
}

fn mock_wav() -> &'static [u8] {
    &[
        b'R', b'I', b'F', b'F', 0x24, 0x00, 0x00, 0x00, b'W', b'A', b'V', b'E', b'f', b'm', b't',
        b' ', 0x10, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x80, 0x3e, 0x00, 0x00, 0x00, 0x7d,
        0x00, 0x00, 0x02, 0x00, 0x10, 0x00, b'd', b'a', b't', b'a', 0x00, 0x00, 0x00, 0x00,
    ]
}

fn multipart_text(body: &mut Vec<u8>, boundary: &str, name: &str, value: &str) -> Result<()> {
    write!(
        body,
        "--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n"
    )?;
    Ok(())
}

fn multipart_file(
    body: &mut Vec<u8>,
    boundary: &str,
    name: &str,
    filename: &str,
    content: &[u8],
) -> Result<()> {
    write!(
        body,
        "--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\nContent-Type: audio/wav\r\n\r\n"
    )?;
    body.extend_from_slice(content);
    body.extend_from_slice(b"\r\n");
    Ok(())
}

fn http_error(operation: &str, error: ureq::Error) -> anyhow::Error {
    match error {
        ureq::Error::Status(status, response) => {
            let mut body = String::new();
            let _ = response
                .into_reader()
                .take(MAX_ERROR_BODY_BYTES)
                .read_to_string(&mut body);
            anyhow!("openai {operation} failed: status={status} body={body}")
        }
        other => anyhow!(other),
    }
}

fn request_timeout(context: &SpeechRequestContext) -> Duration {
    context
        .remaining_until_deadline()
        .map(|remaining| remaining.min(DEFAULT_OPENAI_HTTP_TIMEOUT))
        .unwrap_or(DEFAULT_OPENAI_HTTP_TIMEOUT)
        .max(Duration::from_millis(1))
}

fn run_abortable<T, F>(context: &SpeechRequestContext, work: F) -> Result<T>
where
    T: Send + 'static,
    F: FnOnce() -> Result<T> + Send + 'static,
{
    if context.is_cancelled() {
        bail!(context.cancellation_reason());
    }
    let (sender, receiver) = mpsc::channel();
    std::thread::spawn(move || {
        let _ = sender.send(work());
    });
    loop {
        if context.is_cancelled() {
            bail!(context.cancellation_reason());
        }
        match receiver.recv_timeout(Duration::from_millis(10)) {
            Ok(result) => return result,
            Err(RecvTimeoutError::Timeout) => continue,
            Err(RecvTimeoutError::Disconnected) => {
                bail!("openai request thread ended without response")
            }
        }
    }
}

fn validate_transcription_audio(request: &TranscribeRequest) -> Result<()> {
    if request.max_audio_seconds <= 0.0 {
        return Ok(());
    }
    let info = fs::metadata(&request.audio_path)?;
    if let Some(duration) = wav_duration_seconds(&request.audio_path)? {
        if duration > request.max_audio_seconds {
            return Err(invalid_payload(format!(
                "audio duration {:.3}s exceeds max_audio_seconds {:.3}s",
                duration, request.max_audio_seconds
            )));
        }
        return Ok(());
    }
    let max_bytes = conservative_audio_byte_limit(request);
    if info.len() > max_bytes {
        return Err(invalid_payload(format!(
            "audio size {} bytes exceeds conservative max_audio_seconds cap {} bytes",
            info.len(),
            max_bytes
        )));
    }
    Ok(())
}

pub fn wav_duration_seconds(path: impl AsRef<Path>) -> Result<Option<f64>> {
    let mut file = fs::File::open(path)?;
    let mut header = [0u8; 12];
    if file.read_exact(&mut header).is_err() {
        return Ok(None);
    }
    if &header[0..4] != b"RIFF" || &header[8..12] != b"WAVE" {
        return Ok(None);
    }

    let mut byte_rate = 0u32;
    let mut data_size = 0u64;
    let mut have_format = false;
    let mut have_data = false;
    let mut probed = 12u64;
    while probed < WAV_HEADER_PROBE_BYTES {
        let mut chunk_header = [0u8; 8];
        if file.read_exact(&mut chunk_header).is_err() {
            return Ok(None);
        }
        probed += 8;
        let chunk_id = &chunk_header[0..4];
        let chunk_size = u32::from_le_bytes(chunk_header[4..8].try_into().expect("size"));
        let chunk_size_u64 = u64::from(chunk_size);
        match chunk_id {
            b"fmt " => {
                if chunk_size < 16 {
                    return Ok(None);
                }
                let mut format = [0u8; 16];
                file.read_exact(&mut format)?;
                probed += 16;
                byte_rate = u32::from_le_bytes(format[8..12].try_into().expect("byte rate"));
                have_format = byte_rate > 0;
                skip_chunk_remainder(&mut file, chunk_size_u64 - 16)?;
                probed += chunk_size_u64 - 16 + chunk_size_u64 % 2;
            }
            b"data" => {
                if chunk_size == UNKNOWN_WAV_CHUNK_SIZE {
                    let data_start = file.stream_position()?;
                    let file_size = file.metadata()?.len();
                    if file_size < data_start {
                        return Ok(None);
                    }
                    data_size = file_size - data_start;
                    if have_format {
                        return Ok(Some(data_size as f64 / f64::from(byte_rate)));
                    }
                    return Ok(None);
                }
                data_size = chunk_size_u64;
                have_data = true;
                skip_chunk_remainder(&mut file, chunk_size_u64)?;
                probed += chunk_size_u64 + chunk_size_u64 % 2;
            }
            _ => {
                skip_chunk_remainder(&mut file, chunk_size_u64)?;
                probed += chunk_size_u64 + chunk_size_u64 % 2;
            }
        }
        if have_format && have_data {
            return Ok(Some(data_size as f64 / f64::from(byte_rate)));
        }
    }
    Ok(None)
}

fn skip_chunk_remainder(file: &mut fs::File, chunk_size: u64) -> Result<()> {
    let skip = chunk_size + chunk_size % 2;
    file.seek(SeekFrom::Current(i64::try_from(skip)?))?;
    Ok(())
}

fn normalize_streaming_wav_sizes(path: impl AsRef<Path>) -> Result<()> {
    let mut file = fs::OpenOptions::new().read(true).write(true).open(path)?;
    let file_size = file.metadata()?.len();
    if file_size < 12 {
        return Ok(());
    }
    let mut header = [0u8; 12];
    file.read_exact(&mut header)?;
    if &header[0..4] != b"RIFF" || &header[8..12] != b"WAVE" {
        return Ok(());
    }
    if u32::from_le_bytes(header[4..8].try_into().expect("riff size")) == UNKNOWN_WAV_CHUNK_SIZE {
        write_u32_at(&mut file, 4, u32::try_from(file_size - 8)?)?;
    }
    let mut offset = 12u64;
    while offset + 8 <= file_size && offset < WAV_HEADER_PROBE_BYTES {
        let mut chunk_header = [0u8; 8];
        file.read_exact_at(&mut chunk_header, offset)?;
        let chunk_id = &chunk_header[0..4];
        let chunk_size = u32::from_le_bytes(chunk_header[4..8].try_into().expect("chunk size"));
        let data_start = offset + 8;
        if chunk_id == b"data" {
            if chunk_size == UNKNOWN_WAV_CHUNK_SIZE {
                write_u32_at(
                    &mut file,
                    offset + 4,
                    u32::try_from(file_size - data_start)?,
                )?;
            }
            return Ok(());
        }
        if chunk_size == UNKNOWN_WAV_CHUNK_SIZE {
            return Ok(());
        }
        let chunk_size_u64 = u64::from(chunk_size);
        offset = data_start + chunk_size_u64 + chunk_size_u64 % 2;
    }
    Ok(())
}

trait ReadExactAt {
    fn read_exact_at(&mut self, buffer: &mut [u8], offset: u64) -> Result<()>;
}

impl ReadExactAt for fs::File {
    fn read_exact_at(&mut self, buffer: &mut [u8], offset: u64) -> Result<()> {
        self.seek(SeekFrom::Start(offset))?;
        self.read_exact(buffer)?;
        Ok(())
    }
}

fn write_u32_at(file: &mut fs::File, offset: u64, value: u32) -> Result<()> {
    file.seek(SeekFrom::Start(offset))?;
    file.write_all(&value.to_le_bytes())?;
    Ok(())
}

fn conservative_audio_byte_limit(request: &TranscribeRequest) -> u64 {
    let sample_rate_hz = if request.sample_rate_hz == 0 {
        DEFAULT_STT_SAMPLE_RATE
    } else {
        request.sample_rate_hz
    };
    let channels = if request.channels == 0 {
        DEFAULT_STT_CHANNELS
    } else {
        request.channels
    };
    (request.max_audio_seconds * f64::from(sample_rate_hz * channels * STT_BYTES_PER_SAMPLE)) as u64
        + AUDIO_SIZE_ALLOWANCE
}

#[derive(Deserialize)]
struct OpenAiTranscriptionResponse {
    text: String,
}

#[derive(Deserialize)]
struct OpenAiResponse {
    #[serde(default)]
    output_text: String,
    #[serde(default)]
    output: Vec<OpenAiOutput>,
}

#[derive(Deserialize)]
struct OpenAiOutput {
    #[serde(default)]
    content: Vec<OpenAiContent>,
}

#[derive(Deserialize)]
struct OpenAiContent {
    #[serde(rename = "type")]
    content_type: String,
    text: String,
}

impl OpenAiResponse {
    fn answer_text(&self) -> &str {
        if !self.output_text.is_empty() {
            return &self.output_text;
        }
        for output in &self.output {
            for content in &output.content {
                if content.content_type == "output_text" && !content.text.is_empty() {
                    return &content.text;
                }
            }
        }
        ""
    }
}

fn openai_response_input(history: &[AskTurn], question: &str) -> Vec<serde_json::Value> {
    let mut input = Vec::with_capacity(history.len() + 1);
    for turn in history {
        let role = turn.role.trim().to_ascii_lowercase();
        let text = turn.text.trim();
        if matches!(role.as_str(), "user" | "assistant") && !text.is_empty() {
            input.push(json!({
                "role": role,
                "content": text,
            }));
        }
    }
    input.push(json!({
        "role": "user",
        "content": question,
    }));
    input
}

fn truncate_chars(value: &str, max_chars: usize) -> String {
    value.chars().take(max_chars).collect()
}
