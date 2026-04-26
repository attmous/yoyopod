package provider

import (
	"context"
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
}

func TestNewOpenAIProviderFromEnvUsesDefaultsAndOverrides(t *testing.T) {
	t.Setenv("OPENAI_BASE_URL", "https://openai.test")
	t.Setenv("OPENAI_API_KEY", "env-key")
	t.Setenv("YOYOPOD_CLOUD_STT_MODEL", "env-stt")
	t.Setenv("YOYOPOD_CLOUD_TTS_MODEL", "env-tts")
	t.Setenv("YOYOPOD_CLOUD_TTS_VOICE", "verse")

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
}

func writeTestWAV(t *testing.T, content []byte) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "input.wav")
	if err := os.WriteFile(path, content, 0600); err != nil {
		t.Fatalf("WriteFile returned error: %v", err)
	}
	return path
}

func isMissingAPIKeyError(err error) bool {
	return err != nil && errors.Is(err, ErrMissingAPIKey)
}
