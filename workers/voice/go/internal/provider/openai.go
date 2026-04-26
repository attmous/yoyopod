package provider

import (
	"bytes"
	"context"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const (
	defaultOpenAIBaseURL  = "https://api.openai.com"
	defaultOpenAISTTModel = "gpt-4o-mini-transcribe"
	defaultOpenAITTSModel = "gpt-4o-mini-tts"
	defaultOpenAITTSVoice = "alloy"
	maxErrorBodyBytes     = 4096
	wavHeaderProbeBytes   = 1024 * 1024
	audioSizeAllowance    = 4096
	defaultSTTSampleRate  = 16000
	defaultSTTChannels    = 1
	sttBytesPerSample     = 2
	unknownWAVChunkSize   = int64(0xffffffff)
)

var ErrMissingAPIKey = errors.New("OPENAI_API_KEY is not set")

type OpenAIProvider struct {
	BaseURL  string
	APIKey   string
	STTModel string
	TTSModel string
	TTSVoice string
	Client   *http.Client
}

func NewOpenAIProviderFromEnv() OpenAIProvider {
	return OpenAIProvider{
		BaseURL:  envOrDefault("OPENAI_BASE_URL", defaultOpenAIBaseURL),
		APIKey:   os.Getenv("OPENAI_API_KEY"),
		STTModel: envOrDefault("YOYOPOD_CLOUD_STT_MODEL", defaultOpenAISTTModel),
		TTSModel: envOrDefault("YOYOPOD_CLOUD_TTS_MODEL", defaultOpenAITTSModel),
		TTSVoice: envOrDefault("YOYOPOD_CLOUD_TTS_VOICE", defaultOpenAITTSVoice),
	}
}

func (p OpenAIProvider) Health(ctx context.Context) (HealthResult, error) {
	if err := p.requireAPIKey(); err != nil {
		return HealthResult{}, err
	}
	select {
	case <-ctx.Done():
		return HealthResult{}, ctx.Err()
	default:
		return HealthResult{Healthy: true, Provider: "openai"}, nil
	}
}

func (p OpenAIProvider) Transcribe(ctx context.Context, request TranscribeRequest) (TranscribeResult, error) {
	startedAt := time.Now()
	if err := p.requireAPIKey(); err != nil {
		return TranscribeResult{}, err
	}
	if err := validateTranscriptionAudio(request); err != nil {
		return TranscribeResult{}, err
	}

	audio, err := os.Open(request.AudioPath)
	if err != nil {
		return TranscribeResult{}, err
	}
	defer audio.Close()

	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	filePart, err := writer.CreateFormFile("file", filepath.Base(request.AudioPath))
	if err != nil {
		_ = writer.Close()
		return TranscribeResult{}, err
	}
	if _, err := io.Copy(filePart, audio); err != nil {
		_ = writer.Close()
		return TranscribeResult{}, err
	}
	model := request.Model
	if model == "" {
		model = p.STTModel
	}
	if err := writer.WriteField("model", model); err != nil {
		_ = writer.Close()
		return TranscribeResult{}, err
	}
	if request.Language != "" {
		if err := writer.WriteField("language", request.Language); err != nil {
			_ = writer.Close()
			return TranscribeResult{}, err
		}
	}
	if err := writer.WriteField("response_format", "json"); err != nil {
		_ = writer.Close()
		return TranscribeResult{}, err
	}
	if err := writer.Close(); err != nil {
		return TranscribeResult{}, err
	}

	httpRequest, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		p.urlFor("/v1/audio/transcriptions"),
		&body,
	)
	if err != nil {
		return TranscribeResult{}, err
	}
	httpRequest.Header.Set("Authorization", "Bearer "+p.APIKey)
	httpRequest.Header.Set("Content-Type", writer.FormDataContentType())

	response, err := p.httpClient().Do(httpRequest)
	if err != nil {
		return TranscribeResult{}, err
	}
	defer response.Body.Close()

	if response.StatusCode >= http.StatusBadRequest {
		return TranscribeResult{}, p.httpError("transcription", response)
	}

	var decoded struct {
		Text string `json:"text"`
	}
	if err := json.NewDecoder(response.Body).Decode(&decoded); err != nil {
		return TranscribeResult{}, err
	}
	return TranscribeResult{
		Text:              decoded.Text,
		Confidence:        1.0,
		IsFinal:           true,
		ProviderLatencyMS: time.Since(startedAt).Milliseconds(),
	}, nil
}

func (p OpenAIProvider) Speak(ctx context.Context, request SpeakRequest) (SpeakResult, error) {
	startedAt := time.Now()
	if err := p.requireAPIKey(); err != nil {
		return SpeakResult{}, err
	}

	model := request.Model
	if model == "" {
		model = p.TTSModel
	}
	voice := request.Voice
	if voice == "" {
		voice = p.TTSVoice
	}
	payload := openAISpeechRequest{
		Model:          model,
		Input:          request.Text,
		Voice:          voice,
		ResponseFormat: "wav",
		Instructions:   request.Instructions,
	}
	encoded, err := json.Marshal(payload)
	if err != nil {
		return SpeakResult{}, err
	}
	httpRequest, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		p.urlFor("/v1/audio/speech"),
		bytes.NewReader(encoded),
	)
	if err != nil {
		return SpeakResult{}, err
	}
	httpRequest.Header.Set("Authorization", "Bearer "+p.APIKey)
	httpRequest.Header.Set("Content-Type", "application/json")

	response, err := p.httpClient().Do(httpRequest)
	if err != nil {
		return SpeakResult{}, err
	}
	defer response.Body.Close()

	if response.StatusCode >= http.StatusBadRequest {
		return SpeakResult{}, p.httpError("speech", response)
	}

	output, err := os.CreateTemp("", "yoyopod-cloud-tts-*.wav")
	if err != nil {
		return SpeakResult{}, err
	}
	outputPath := output.Name()
	if _, err := io.Copy(output, response.Body); err != nil {
		_ = output.Close()
		_ = os.Remove(outputPath)
		return SpeakResult{}, err
	}
	if err := output.Close(); err != nil {
		_ = os.Remove(outputPath)
		return SpeakResult{}, err
	}

	sampleRateHz := request.SampleRateHz
	if sampleRateHz == 0 {
		sampleRateHz = 16000
	}
	return SpeakResult{
		AudioPath:         outputPath,
		Format:            "wav",
		SampleRateHz:      sampleRateHz,
		ProviderLatencyMS: time.Since(startedAt).Milliseconds(),
	}, nil
}

type openAISpeechRequest struct {
	Model          string `json:"model"`
	Input          string `json:"input"`
	Voice          string `json:"voice"`
	ResponseFormat string `json:"response_format"`
	Instructions   string `json:"instructions,omitempty"`
}

func (p OpenAIProvider) requireAPIKey() error {
	if p.APIKey == "" {
		return ErrMissingAPIKey
	}
	return nil
}

func (p OpenAIProvider) urlFor(path string) string {
	baseURL := p.BaseURL
	if baseURL == "" {
		baseURL = defaultOpenAIBaseURL
	}
	return strings.TrimRight(baseURL, "/") + path
}

func (p OpenAIProvider) httpClient() *http.Client {
	if p.Client != nil {
		return p.Client
	}
	return &http.Client{Timeout: 30 * time.Second}
}

func (p OpenAIProvider) httpError(operation string, response *http.Response) error {
	body, _ := io.ReadAll(io.LimitReader(response.Body, maxErrorBodyBytes))
	return fmt.Errorf("openai %s failed: status=%d body=%s", operation, response.StatusCode, string(body))
}

func validateTranscriptionAudio(request TranscribeRequest) error {
	if request.MaxAudioSeconds <= 0 {
		return nil
	}
	info, err := os.Stat(request.AudioPath)
	if err != nil {
		return err
	}
	if duration, ok := wavDurationSeconds(request.AudioPath); ok {
		if duration > request.MaxAudioSeconds {
			return InvalidPayload(fmt.Sprintf(
				"audio duration %.3fs exceeds max_audio_seconds %.3fs",
				duration,
				request.MaxAudioSeconds,
			))
		}
		return nil
	}
	maxBytes := conservativeAudioByteLimit(request)
	if info.Size() > maxBytes {
		return InvalidPayload(fmt.Sprintf(
			"audio size %d bytes exceeds conservative max_audio_seconds cap %d bytes",
			info.Size(),
			maxBytes,
		))
	}
	return nil
}

func wavDurationSeconds(path string) (float64, bool) {
	file, err := os.Open(path)
	if err != nil {
		return 0, false
	}
	defer file.Close()

	header := make([]byte, 12)
	if _, err := io.ReadFull(file, header); err != nil {
		return 0, false
	}
	if string(header[0:4]) != "RIFF" || string(header[8:12]) != "WAVE" {
		return 0, false
	}

	var byteRate uint32
	var dataSize int64
	var haveFormat bool
	var haveData bool
	var probed int64 = 12
	for probed < wavHeaderProbeBytes {
		chunkHeader := make([]byte, 8)
		if _, err := io.ReadFull(file, chunkHeader); err != nil {
			return 0, false
		}
		probed += int64(len(chunkHeader))
		chunkID := string(chunkHeader[0:4])
		chunkSize := int64(binary.LittleEndian.Uint32(chunkHeader[4:8]))
		switch chunkID {
		case "fmt ":
			if chunkSize < 16 {
				return 0, false
			}
			format := make([]byte, 16)
			if _, err := io.ReadFull(file, format); err != nil {
				return 0, false
			}
			probed += int64(len(format))
			byteRate = binary.LittleEndian.Uint32(format[8:12])
			haveFormat = byteRate > 0
			if _, err := file.Seek(chunkSize-16+chunkSize%2, io.SeekCurrent); err != nil {
				return 0, false
			}
			probed += chunkSize - 16 + chunkSize%2
		case "data":
			if chunkSize == unknownWAVChunkSize {
				dataStart, err := file.Seek(0, io.SeekCurrent)
				if err != nil {
					return 0, false
				}
				info, err := file.Stat()
				if err != nil || info.Size() < dataStart {
					return 0, false
				}
				dataSize = info.Size() - dataStart
				haveData = true
				if haveFormat {
					return float64(dataSize) / float64(byteRate), true
				}
				return 0, false
			}
			dataSize = chunkSize
			haveData = true
			if _, err := file.Seek(chunkSize+chunkSize%2, io.SeekCurrent); err != nil {
				return 0, false
			}
			probed += chunkSize + chunkSize%2
		default:
			if _, err := file.Seek(chunkSize+chunkSize%2, io.SeekCurrent); err != nil {
				return 0, false
			}
			probed += chunkSize + chunkSize%2
		}
		if haveFormat && haveData {
			return float64(dataSize) / float64(byteRate), true
		}
	}
	return 0, false
}

func conservativeAudioByteLimit(request TranscribeRequest) int64 {
	sampleRateHz := request.SampleRateHz
	if sampleRateHz <= 0 {
		sampleRateHz = defaultSTTSampleRate
	}
	channels := request.Channels
	if channels <= 0 {
		channels = defaultSTTChannels
	}
	limit := request.MaxAudioSeconds * float64(sampleRateHz*channels*sttBytesPerSample)
	return int64(limit) + audioSizeAllowance
}

func envOrDefault(key string, defaultValue string) string {
	value := os.Getenv(key)
	if value == "" {
		return defaultValue
	}
	return value
}

var _ Provider = OpenAIProvider{}
