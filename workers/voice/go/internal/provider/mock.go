package provider

import (
	"context"
	"os"
	"time"
)

type MockProvider struct{}

func (MockProvider) Health(ctx context.Context) (HealthResult, error) {
	select {
	case <-ctx.Done():
		return HealthResult{}, ctx.Err()
	default:
		return HealthResult{Healthy: true, Provider: "mock"}, nil
	}
}

func (MockProvider) Transcribe(ctx context.Context, request TranscribeRequest) (TranscribeResult, error) {
	startedAt := time.Now()
	select {
	case <-ctx.Done():
		return TranscribeResult{}, ctx.Err()
	default:
	}

	text := os.Getenv("YOYOPOD_MOCK_TRANSCRIPT")
	if text == "" {
		text = "play music"
	}
	return TranscribeResult{
		Text:              text,
		Confidence:        1.0,
		IsFinal:           true,
		ProviderLatencyMS: time.Since(startedAt).Milliseconds(),
	}, nil
}

func (MockProvider) Speak(ctx context.Context, request SpeakRequest) (SpeakResult, error) {
	startedAt := time.Now()
	select {
	case <-ctx.Done():
		return SpeakResult{}, ctx.Err()
	default:
	}

	output, err := os.CreateTemp("", "yoyopod-mock-tts-*.wav")
	if err != nil {
		return SpeakResult{}, err
	}
	defer output.Close()

	if _, err := output.Write(mockWAV()); err != nil {
		_ = os.Remove(output.Name())
		return SpeakResult{}, err
	}
	sampleRateHz := request.SampleRateHz
	if sampleRateHz == 0 {
		sampleRateHz = 16000
	}
	return SpeakResult{
		AudioPath:         output.Name(),
		Format:            "wav",
		SampleRateHz:      sampleRateHz,
		DurationMS:        100,
		ProviderLatencyMS: time.Since(startedAt).Milliseconds(),
	}, nil
}

func (MockProvider) Ask(ctx context.Context, request AskRequest) (AskResult, error) {
	startedAt := time.Now()
	select {
	case <-ctx.Done():
		return AskResult{}, ctx.Err()
	default:
	}

	answer := os.Getenv("YOYOPOD_MOCK_ASK_ANSWER")
	if answer == "" {
		answer = "I can answer that in a small, friendly way."
	}
	model := request.Model
	if model == "" {
		model = "mock"
	}
	return AskResult{
		Answer:            answer,
		Model:             model,
		ProviderLatencyMS: time.Since(startedAt).Milliseconds(),
	}, nil
}

func mockWAV() []byte {
	return []byte{
		'R', 'I', 'F', 'F',
		0x24, 0x00, 0x00, 0x00,
		'W', 'A', 'V', 'E',
		'f', 'm', 't', ' ',
		0x10, 0x00, 0x00, 0x00,
		0x01, 0x00,
		0x01, 0x00,
		0x80, 0x3e, 0x00, 0x00,
		0x00, 0x7d, 0x00, 0x00,
		0x02, 0x00,
		0x10, 0x00,
		'd', 'a', 't', 'a',
		0x00, 0x00, 0x00, 0x00,
	}
}
