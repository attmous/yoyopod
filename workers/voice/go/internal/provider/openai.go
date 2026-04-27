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
	defaultOpenAIAskModel = "gpt-4.1-mini"
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
	AskModel string
	STTModel string
	TTSModel string
	TTSVoice string
	Client   *http.Client
}

func NewOpenAIProviderFromEnv() OpenAIProvider {
	return OpenAIProvider{
		BaseURL:  envOrDefault("OPENAI_BASE_URL", defaultOpenAIBaseURL),
		APIKey:   os.Getenv("OPENAI_API_KEY"),
		AskModel: envOrDefault("YOYOPOD_CLOUD_ASK_MODEL", defaultOpenAIAskModel),
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
	if err := normalizeStreamingWAVSizes(outputPath); err != nil {
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

func (p OpenAIProvider) Ask(ctx context.Context, request AskRequest) (AskResult, error) {
	startedAt := time.Now()
	if err := p.requireAPIKey(); err != nil {
		return AskResult{}, err
	}
	question := strings.TrimSpace(request.Question)
	if question == "" {
		return AskResult{}, InvalidPayload("question is required")
	}

	model := request.Model
	if model == "" {
		model = p.AskModel
	}
	if model == "" {
		model = defaultOpenAIAskModel
	}
	payload := openAIResponseRequest{
		Model:        model,
		Instructions: strings.TrimSpace(request.Instructions),
		Input:        openAIResponseInput(request.History, question),
	}
	encoded, err := json.Marshal(payload)
	if err != nil {
		return AskResult{}, err
	}
	httpRequest, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		p.urlFor("/v1/responses"),
		bytes.NewReader(encoded),
	)
	if err != nil {
		return AskResult{}, err
	}
	httpRequest.Header.Set("Authorization", "Bearer "+p.APIKey)
	httpRequest.Header.Set("Content-Type", "application/json")

	response, err := p.httpClient().Do(httpRequest)
	if err != nil {
		return AskResult{}, err
	}
	defer response.Body.Close()

	if response.StatusCode >= http.StatusBadRequest {
		return AskResult{}, p.httpError("response", response)
	}

	var decoded openAIResponse
	if err := json.NewDecoder(response.Body).Decode(&decoded); err != nil {
		return AskResult{}, err
	}
	answer := strings.TrimSpace(decoded.answerText())
	if request.MaxOutputChars > 0 {
		answer = strings.TrimSpace(truncateRunes(answer, request.MaxOutputChars))
	}
	if answer == "" {
		return AskResult{}, fmt.Errorf("openai response returned empty answer")
	}
	return AskResult{
		Answer:            answer,
		Model:             model,
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

type openAIResponseRequest struct {
	Model        string                       `json:"model"`
	Instructions string                       `json:"instructions"`
	Input        []openAIResponseInputMessage `json:"input"`
}

type openAIResponseInputMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type openAIResponse struct {
	OutputText string `json:"output_text"`
	Output     []struct {
		Content []struct {
			Type string `json:"type"`
			Text string `json:"text"`
		} `json:"content"`
	} `json:"output"`
}

func (r openAIResponse) answerText() string {
	if r.OutputText != "" {
		return r.OutputText
	}
	for _, output := range r.Output {
		for _, content := range output.Content {
			if content.Type == "output_text" && content.Text != "" {
				return content.Text
			}
		}
	}
	return ""
}

func openAIResponseInput(history []AskTurn, question string) []openAIResponseInputMessage {
	input := make([]openAIResponseInputMessage, 0, len(history)+1)
	for _, turn := range history {
		role := strings.ToLower(strings.TrimSpace(turn.Role))
		text := strings.TrimSpace(turn.Text)
		if !isValidResponseInputRole(role) || text == "" {
			continue
		}
		input = append(input, openAIResponseInputMessage{
			Role:    role,
			Content: text,
		})
	}
	input = append(input, openAIResponseInputMessage{
		Role:    "user",
		Content: question,
	})
	return input
}

func isValidResponseInputRole(role string) bool {
	return role == "user" || role == "assistant"
}

func truncateRunes(value string, maxChars int) string {
	runes := []rune(value)
	if len(runes) <= maxChars {
		return value
	}
	return string(runes[:maxChars])
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

func normalizeStreamingWAVSizes(path string) error {
	file, err := os.OpenFile(path, os.O_RDWR, 0600)
	if err != nil {
		return err
	}
	defer file.Close()

	info, err := file.Stat()
	if err != nil {
		return err
	}
	if info.Size() < 12 {
		return nil
	}
	if info.Size()-8 > int64(^uint32(0)) {
		return fmt.Errorf("wav file too large to normalize: %d bytes", info.Size())
	}

	header := make([]byte, 12)
	if _, err := io.ReadFull(file, header); err != nil {
		return nil
	}
	if string(header[0:4]) != "RIFF" || string(header[8:12]) != "WAVE" {
		return nil
	}

	if int64(binary.LittleEndian.Uint32(header[4:8])) == unknownWAVChunkSize {
		if err := writeUint32At(file, 4, uint32(info.Size()-8)); err != nil {
			return err
		}
	}

	var offset int64 = 12
	for offset+8 <= info.Size() && offset < wavHeaderProbeBytes {
		chunkHeader := make([]byte, 8)
		if _, err := file.ReadAt(chunkHeader, offset); err != nil {
			return nil
		}
		chunkID := string(chunkHeader[0:4])
		chunkSize := int64(binary.LittleEndian.Uint32(chunkHeader[4:8]))
		dataStart := offset + 8
		if chunkID == "data" {
			if chunkSize == unknownWAVChunkSize {
				actualDataSize := info.Size() - dataStart
				if actualDataSize < 0 || actualDataSize > int64(^uint32(0)) {
					return fmt.Errorf(
						"wav data chunk too large to normalize: %d bytes",
						actualDataSize,
					)
				}
				return writeUint32At(file, offset+4, uint32(actualDataSize))
			}
			return nil
		}
		if chunkSize == unknownWAVChunkSize {
			return nil
		}
		offset = dataStart + chunkSize + chunkSize%2
	}
	return nil
}

func writeUint32At(file *os.File, offset int64, value uint32) error {
	buffer := make([]byte, 4)
	binary.LittleEndian.PutUint32(buffer, value)
	_, err := file.WriteAt(buffer, offset)
	return err
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
