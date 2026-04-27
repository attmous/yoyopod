package provider

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestOpenAIProviderTranscribeBuildsMultipartRequest(t *testing.T) {
	audioPath := writeTestWAV(t, []byte("RIFF-test-audio-WAVE"))
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/audio/transcriptions" {
			t.Fatalf("path = %q, want /v1/audio/transcriptions", r.URL.Path)
		}
		if r.Header.Get("Authorization") != "Bearer test-key" {
			t.Fatalf("Authorization = %q, want bearer token", r.Header.Get("Authorization"))
		}
		if !strings.HasPrefix(r.Header.Get("Content-Type"), "multipart/form-data;") {
			t.Fatalf("Content-Type = %q, want multipart/form-data", r.Header.Get("Content-Type"))
		}
		if err := r.ParseMultipartForm(1024 * 1024); err != nil {
			t.Fatalf("ParseMultipartForm returned error: %v", err)
		}
		if got := r.FormValue("model"); got != "custom-stt" {
			t.Fatalf("model = %q, want custom-stt", got)
		}
		if got := r.FormValue("language"); got != "en" {
			t.Fatalf("language = %q, want en", got)
		}
		if got := r.FormValue("response_format"); got != "json" {
			t.Fatalf("response_format = %q, want json", got)
		}
		file, header, err := r.FormFile("file")
		if err != nil {
			t.Fatalf("FormFile returned error: %v", err)
		}
		defer file.Close()
		if header.Filename != filepath.Base(audioPath) {
			t.Fatalf("filename = %q, want %q", header.Filename, filepath.Base(audioPath))
		}
		content, err := io.ReadAll(file)
		if err != nil {
			t.Fatalf("ReadAll uploaded file returned error: %v", err)
		}
		if string(content) != "RIFF-test-audio-WAVE" {
			t.Fatalf("uploaded content = %q, want test audio", content)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"text":"play music"}`))
	}))
	defer server.Close()

	result, err := OpenAIProvider{
		BaseURL:  server.URL,
		APIKey:   "test-key",
		STTModel: "default-stt",
		TTSModel: "default-tts",
		TTSVoice: "alloy",
	}.Transcribe(context.Background(), TranscribeRequest{
		AudioPath: audioPath,
		Language:  "en",
		Model:     "custom-stt",
	})

	if err != nil {
		t.Fatalf("Transcribe returned error: %v", err)
	}
	if result.Text != "play music" {
		t.Fatalf("Text = %q, want play music", result.Text)
	}
	if result.Confidence != 1.0 {
		t.Fatalf("Confidence = %v, want 1.0", result.Confidence)
	}
	if !result.IsFinal {
		t.Fatalf("IsFinal = false, want true")
	}
}

func TestOpenAIProviderTranscribeRejectsOverLimitWAVBeforeUpload(t *testing.T) {
	audioPath := writeTestWAV(t, makeTestWAV(16000, 1, 16, 2*16000*2))
	uploaded := false
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		uploaded = true
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer server.Close()

	_, err := OpenAIProvider{
		BaseURL: server.URL,
		APIKey:  "test-key",
	}.Transcribe(context.Background(), TranscribeRequest{
		AudioPath:       audioPath,
		MaxAudioSeconds: 1,
	})

	if err == nil {
		t.Fatalf("Transcribe returned nil error for over-limit WAV")
	}
	if uploaded {
		t.Fatalf("Transcribe uploaded over-limit WAV")
	}
}

func TestOpenAIProviderTranscribeRejectsOverLimitUnknownAudioBeforeUpload(t *testing.T) {
	audioPath := filepath.Join(t.TempDir(), "input.bin")
	if err := os.WriteFile(audioPath, make([]byte, 40000), 0600); err != nil {
		t.Fatalf("WriteFile returned error: %v", err)
	}
	uploaded := false
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		uploaded = true
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer server.Close()

	_, err := OpenAIProvider{
		BaseURL: server.URL,
		APIKey:  "test-key",
	}.Transcribe(context.Background(), TranscribeRequest{
		AudioPath:       audioPath,
		MaxAudioSeconds: 1,
		SampleRateHz:    16000,
		Channels:        1,
	})

	if err == nil {
		t.Fatalf("Transcribe returned nil error for over-limit unknown audio")
	}
	if uploaded {
		t.Fatalf("Transcribe uploaded over-limit unknown audio")
	}
}

func TestWAVDurationUsesActualFileSizeForStreamingDataChunk(t *testing.T) {
	dataBytes := 24000 * 2
	audioPath := writeTestWAV(t, makeStreamingDataSizeWAV(24000, 1, 16, dataBytes))

	duration, ok := wavDurationSeconds(audioPath)

	if !ok {
		t.Fatalf("wavDurationSeconds ok = false, want true")
	}
	if duration != 1.0 {
		t.Fatalf("duration = %v, want 1.0", duration)
	}
}

func TestOpenAIProviderSpeakPostsJSONAndWritesWAV(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/audio/speech" {
			t.Fatalf("path = %q, want /v1/audio/speech", r.URL.Path)
		}
		if r.Header.Get("Authorization") != "Bearer test-key" {
			t.Fatalf("Authorization = %q, want bearer token", r.Header.Get("Authorization"))
		}
		if r.Header.Get("Content-Type") != "application/json" {
			t.Fatalf("Content-Type = %q, want application/json", r.Header.Get("Content-Type"))
		}
		var payload map[string]string
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Fatalf("Decode returned error: %v", err)
		}
		want := map[string]string{
			"model":           "custom-tts",
			"input":           "Playing music",
			"voice":           "verse",
			"instructions":    "Speak warmly.",
			"response_format": "wav",
		}
		for key, value := range want {
			if payload[key] != value {
				t.Fatalf("%s = %q, want %q in payload %#v", key, payload[key], value, payload)
			}
		}
		w.Header().Set("Content-Type", "audio/wav")
		_, _ = w.Write([]byte("RIFF-test-output-WAVE"))
	}))
	defer server.Close()

	result, err := OpenAIProvider{
		BaseURL:  server.URL,
		APIKey:   "test-key",
		STTModel: "default-stt",
		TTSModel: "default-tts",
		TTSVoice: "alloy",
	}.Speak(context.Background(), SpeakRequest{
		Text:         "Playing music",
		Model:        "custom-tts",
		Voice:        "verse",
		Instructions: "Speak warmly.",
	})

	if err != nil {
		t.Fatalf("Speak returned error: %v", err)
	}
	t.Cleanup(func() { _ = os.Remove(result.AudioPath) })
	if filepath.Base(result.AudioPath) == result.AudioPath {
		t.Fatalf("AudioPath = %q, want temp file path", result.AudioPath)
	}
	if filepath.Ext(result.AudioPath) != ".wav" {
		t.Fatalf("AudioPath = %q, want .wav extension", result.AudioPath)
	}
	if result.Format != "wav" {
		t.Fatalf("Format = %q, want wav", result.Format)
	}
	if result.SampleRateHz != 16000 {
		t.Fatalf("SampleRateHz = %d, want default 16000", result.SampleRateHz)
	}
	content, err := os.ReadFile(result.AudioPath)
	if err != nil {
		t.Fatalf("ReadFile returned error: %v", err)
	}
	if string(content) != "RIFF-test-output-WAVE" {
		t.Fatalf("output content = %q, want wav bytes", content)
	}
}

func TestOpenAIProviderSpeakNormalizesStreamingWAVSizes(t *testing.T) {
	dataBytes := 24000 * 2
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "audio/wav")
		_, _ = w.Write(makeStreamingDataSizeWAV(24000, 1, 16, dataBytes))
	}))
	defer server.Close()

	result, err := OpenAIProvider{
		BaseURL: server.URL,
		APIKey:  "test-key",
	}.Speak(context.Background(), SpeakRequest{
		Text: "Playing music",
	})

	if err != nil {
		t.Fatalf("Speak returned error: %v", err)
	}
	t.Cleanup(func() { _ = os.Remove(result.AudioPath) })

	content, err := os.ReadFile(result.AudioPath)
	if err != nil {
		t.Fatalf("ReadFile returned error: %v", err)
	}
	if got, want := binary.LittleEndian.Uint32(content[4:8]), uint32(len(content)-8); got != want {
		t.Fatalf("RIFF size = %d, want %d", got, want)
	}
	if got, want := binary.LittleEndian.Uint32(content[40:44]), uint32(dataBytes); got != want {
		t.Fatalf("data size = %d, want %d", got, want)
	}
	if duration, ok := wavDurationSeconds(result.AudioPath); !ok || duration != 1.0 {
		t.Fatalf("wavDurationSeconds = %v, %v; want 1.0, true", duration, ok)
	}
}

func TestOpenAIProviderAskPostsResponsesRequestAndParsesOutputText(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/responses" {
			t.Fatalf("path = %q, want /v1/responses", r.URL.Path)
		}
		if r.Header.Get("Authorization") != "Bearer test-key" {
			t.Fatalf("Authorization = %q, want bearer token", r.Header.Get("Authorization"))
		}
		if r.Header.Get("Content-Type") != "application/json" {
			t.Fatalf("Content-Type = %q, want application/json", r.Header.Get("Content-Type"))
		}
		var payload struct {
			Model        string `json:"model"`
			Instructions string `json:"instructions"`
			Input        []struct {
				Role    string `json:"role"`
				Content string `json:"content"`
			} `json:"input"`
		}
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Fatalf("Decode returned error: %v", err)
		}
		if payload.Model != "custom-ask" {
			t.Fatalf("model = %q, want custom-ask", payload.Model)
		}
		if payload.Instructions != "Answer gently." {
			t.Fatalf("instructions = %q, want Answer gently.", payload.Instructions)
		}
		wantInput := []struct {
			role    string
			content string
		}{
			{role: "user", content: "Earlier question"},
			{role: "assistant", content: "Earlier answer"},
			{role: "user", content: "What now?"},
		}
		if len(payload.Input) != len(wantInput) {
			t.Fatalf("input length = %d, want %d in %#v", len(payload.Input), len(wantInput), payload.Input)
		}
		for index, want := range wantInput {
			if payload.Input[index].Role != want.role || payload.Input[index].Content != want.content {
				t.Fatalf("input[%d] = %#v, want role=%q content=%q", index, payload.Input[index], want.role, want.content)
			}
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"output_text":"  A small answer.  "}`))
	}))
	defer server.Close()

	result, err := OpenAIProvider{
		BaseURL:  server.URL,
		APIKey:   "test-key",
		AskModel: "default-ask",
	}.Ask(context.Background(), AskRequest{
		Question:     "What now?",
		Model:        "custom-ask",
		Instructions: "Answer gently.",
		History: []AskTurn{
			{Role: "user", Text: "Earlier question"},
			{Role: "assistant", Text: "Earlier answer"},
			{Role: "tool", Text: "ignored role"},
			{Role: "user", Text: "   "},
		},
	})

	if err != nil {
		t.Fatalf("Ask returned error: %v", err)
	}
	if result.Answer != "A small answer." {
		t.Fatalf("Answer = %q, want trimmed output_text", result.Answer)
	}
	if result.Model != "custom-ask" {
		t.Fatalf("Model = %q, want custom-ask", result.Model)
	}
}

func TestOpenAIProviderAskParsesStructuredOutputFallbackAndTruncates(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"output": [
				{
					"content": [
						{"type": "summary_text", "text": "ignored"},
						{"type": "output_text", "text": "Structured answer"}
					]
				}
			]
		}`))
	}))
	defer server.Close()

	result, err := OpenAIProvider{
		BaseURL:  server.URL,
		APIKey:   "test-key",
		AskModel: "default-ask",
	}.Ask(context.Background(), AskRequest{
		Question:       "What now?",
		MaxOutputChars: 10,
	})

	if err != nil {
		t.Fatalf("Ask returned error: %v", err)
	}
	if result.Answer != "Structured" {
		t.Fatalf("Answer = %q, want truncated structured output", result.Answer)
	}
	if result.Model != "default-ask" {
		t.Fatalf("Model = %q, want default-ask", result.Model)
	}
}

func TestOpenAIProviderReturnsMissingAPIKeyErrors(t *testing.T) {
	provider := OpenAIProvider{BaseURL: "https://example.test"}

	if _, err := provider.Health(context.Background()); !isMissingAPIKeyError(err) {
		t.Fatalf("Health error = %v, want missing API key", err)
	}
	if _, err := provider.Transcribe(context.Background(), TranscribeRequest{}); !isMissingAPIKeyError(err) {
		t.Fatalf("Transcribe error = %v, want missing API key", err)
	}
	if _, err := provider.Speak(context.Background(), SpeakRequest{}); !isMissingAPIKeyError(err) {
		t.Fatalf("Speak error = %v, want missing API key", err)
	}
	if _, err := provider.Ask(context.Background(), AskRequest{Question: "hello"}); !isMissingAPIKeyError(err) {
		t.Fatalf("Ask error = %v, want missing API key", err)
	}
}

func TestNewOpenAIProviderFromEnvUsesDefaultsWhenEnvUnset(t *testing.T) {
	unsetEnv(t, "OPENAI_BASE_URL")
	unsetEnv(t, "OPENAI_API_KEY")
	unsetEnv(t, "YOYOPOD_CLOUD_STT_MODEL")
	unsetEnv(t, "YOYOPOD_CLOUD_TTS_MODEL")
	unsetEnv(t, "YOYOPOD_CLOUD_TTS_VOICE")
	unsetEnv(t, "YOYOPOD_CLOUD_ASK_MODEL")

	provider := NewOpenAIProviderFromEnv()

	if provider.BaseURL != "https://api.openai.com" {
		t.Fatalf("BaseURL = %q, want https://api.openai.com", provider.BaseURL)
	}
	if provider.STTModel != "gpt-4o-mini-transcribe" {
		t.Fatalf("STTModel = %q, want gpt-4o-mini-transcribe", provider.STTModel)
	}
	if provider.TTSModel != "gpt-4o-mini-tts" {
		t.Fatalf("TTSModel = %q, want gpt-4o-mini-tts", provider.TTSModel)
	}
	if provider.TTSVoice != "alloy" {
		t.Fatalf("TTSVoice = %q, want alloy", provider.TTSVoice)
	}
	if provider.AskModel != "gpt-4.1-mini" {
		t.Fatalf("AskModel = %q, want gpt-4.1-mini", provider.AskModel)
	}
}

func TestNewOpenAIProviderFromEnvUsesDefaultsWhenEnvEmpty(t *testing.T) {
	t.Setenv("OPENAI_BASE_URL", "")
	t.Setenv("YOYOPOD_CLOUD_STT_MODEL", "")
	t.Setenv("YOYOPOD_CLOUD_TTS_MODEL", "")
	t.Setenv("YOYOPOD_CLOUD_TTS_VOICE", "")
	t.Setenv("YOYOPOD_CLOUD_ASK_MODEL", "")

	provider := NewOpenAIProviderFromEnv()

	if provider.BaseURL != "https://api.openai.com" {
		t.Fatalf("BaseURL = %q, want https://api.openai.com", provider.BaseURL)
	}
	if provider.STTModel != "gpt-4o-mini-transcribe" {
		t.Fatalf("STTModel = %q, want gpt-4o-mini-transcribe", provider.STTModel)
	}
	if provider.TTSModel != "gpt-4o-mini-tts" {
		t.Fatalf("TTSModel = %q, want gpt-4o-mini-tts", provider.TTSModel)
	}
	if provider.TTSVoice != "alloy" {
		t.Fatalf("TTSVoice = %q, want alloy", provider.TTSVoice)
	}
	if provider.AskModel != "gpt-4.1-mini" {
		t.Fatalf("AskModel = %q, want gpt-4.1-mini", provider.AskModel)
	}
}

func TestNewOpenAIProviderFromEnvUsesOverrides(t *testing.T) {
	t.Setenv("OPENAI_BASE_URL", "https://openai.test")
	t.Setenv("OPENAI_API_KEY", "env-key")
	t.Setenv("YOYOPOD_CLOUD_STT_MODEL", "env-stt")
	t.Setenv("YOYOPOD_CLOUD_TTS_MODEL", "env-tts")
	t.Setenv("YOYOPOD_CLOUD_TTS_VOICE", "verse")
	t.Setenv("YOYOPOD_CLOUD_ASK_MODEL", "env-ask")

	provider := NewOpenAIProviderFromEnv()

	if provider.BaseURL != "https://openai.test" {
		t.Fatalf("BaseURL = %q, want env override", provider.BaseURL)
	}
	if provider.APIKey != "env-key" {
		t.Fatalf("APIKey = %q, want env-key", provider.APIKey)
	}
	if provider.STTModel != "env-stt" {
		t.Fatalf("STTModel = %q, want env-stt", provider.STTModel)
	}
	if provider.TTSModel != "env-tts" {
		t.Fatalf("TTSModel = %q, want env-tts", provider.TTSModel)
	}
	if provider.TTSVoice != "verse" {
		t.Fatalf("TTSVoice = %q, want verse", provider.TTSVoice)
	}
	if provider.AskModel != "env-ask" {
		t.Fatalf("AskModel = %q, want env-ask", provider.AskModel)
	}
}

func writeTestWAV(t *testing.T, content []byte) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "input.wav")
	if err := os.WriteFile(path, content, 0600); err != nil {
		t.Fatalf("WriteFile returned error: %v", err)
	}
	return path
}

func makeTestWAV(sampleRateHz int, channels int, bitsPerSample int, dataBytes int) []byte {
	blockAlign := channels * bitsPerSample / 8
	byteRate := sampleRateHz * blockAlign
	riffSize := 36 + dataBytes
	wav := make([]byte, 44+dataBytes)
	copy(wav[0:4], "RIFF")
	putUint32LE(wav[4:8], uint32(riffSize))
	copy(wav[8:12], "WAVE")
	copy(wav[12:16], "fmt ")
	putUint32LE(wav[16:20], 16)
	putUint16LE(wav[20:22], 1)
	putUint16LE(wav[22:24], uint16(channels))
	putUint32LE(wav[24:28], uint32(sampleRateHz))
	putUint32LE(wav[28:32], uint32(byteRate))
	putUint16LE(wav[32:34], uint16(blockAlign))
	putUint16LE(wav[34:36], uint16(bitsPerSample))
	copy(wav[36:40], "data")
	putUint32LE(wav[40:44], uint32(dataBytes))
	return wav
}

func makeStreamingDataSizeWAV(sampleRateHz int, channels int, bitsPerSample int, dataBytes int) []byte {
	wav := makeTestWAV(sampleRateHz, channels, bitsPerSample, dataBytes)
	putUint32LE(wav[4:8], uint32(unknownWAVChunkSize))
	putUint32LE(wav[40:44], uint32(unknownWAVChunkSize))
	return wav
}

func putUint16LE(target []byte, value uint16) {
	target[0] = byte(value)
	target[1] = byte(value >> 8)
}

func putUint32LE(target []byte, value uint32) {
	target[0] = byte(value)
	target[1] = byte(value >> 8)
	target[2] = byte(value >> 16)
	target[3] = byte(value >> 24)
}

func isMissingAPIKeyError(err error) bool {
	return err != nil && errors.Is(err, ErrMissingAPIKey)
}

func unsetEnv(t *testing.T, key string) {
	t.Helper()
	previous, existed := os.LookupEnv(key)
	if err := os.Unsetenv(key); err != nil {
		t.Fatalf("Unsetenv(%q) returned error: %v", key, err)
	}
	t.Cleanup(func() {
		if existed {
			_ = os.Setenv(key, previous)
			return
		}
		_ = os.Unsetenv(key)
	})
}
