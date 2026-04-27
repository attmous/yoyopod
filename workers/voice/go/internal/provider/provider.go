package provider

import (
	"context"
	"errors"
)

type Provider interface {
	Health(context.Context) (HealthResult, error)
	Transcribe(context.Context, TranscribeRequest) (TranscribeResult, error)
	Speak(context.Context, SpeakRequest) (SpeakResult, error)
	Ask(context.Context, AskRequest) (AskResult, error)
}

type InvalidPayloadError struct {
	Message string
}

func (e InvalidPayloadError) Error() string {
	return e.Message
}

func InvalidPayload(message string) error {
	return InvalidPayloadError{Message: message}
}

func IsInvalidPayload(err error) bool {
	var target InvalidPayloadError
	return errors.As(err, &target)
}

type HealthResult struct {
	Healthy  bool   `json:"healthy"`
	Provider string `json:"provider"`
	Message  string `json:"message,omitempty"`
}

type TranscribeRequest struct {
	AudioPath            string  `json:"audio_path"`
	Format               string  `json:"format"`
	SampleRateHz         int     `json:"sample_rate_hz"`
	Channels             int     `json:"channels"`
	Language             string  `json:"language"`
	Model                string  `json:"model"`
	MaxAudioSeconds      float64 `json:"max_audio_seconds"`
	DeleteInputOnSuccess bool    `json:"delete_input_on_success"`
}

type TranscribeResult struct {
	Text              string  `json:"text"`
	Confidence        float64 `json:"confidence"`
	IsFinal           bool    `json:"is_final"`
	ProviderLatencyMS int64   `json:"provider_latency_ms,omitempty"`
	AudioDurationMS   int64   `json:"audio_duration_ms,omitempty"`
}

type SpeakRequest struct {
	Text         string `json:"text"`
	Voice        string `json:"voice"`
	Model        string `json:"model"`
	Instructions string `json:"instructions"`
	Format       string `json:"format"`
	SampleRateHz int    `json:"sample_rate_hz"`
}

type SpeakResult struct {
	AudioPath         string `json:"audio_path"`
	Format            string `json:"format"`
	SampleRateHz      int    `json:"sample_rate_hz"`
	DurationMS        int64  `json:"duration_ms,omitempty"`
	ProviderLatencyMS int64  `json:"provider_latency_ms,omitempty"`
}

type AskTurn struct {
	Role string `json:"role"`
	Text string `json:"text"`
}

type AskRequest struct {
	Question       string    `json:"question"`
	History        []AskTurn `json:"history"`
	Model          string    `json:"model"`
	Instructions   string    `json:"instructions"`
	MaxOutputChars int       `json:"max_output_chars"`
}

type AskResult struct {
	Answer            string `json:"answer"`
	Model             string `json:"model"`
	ProviderLatencyMS int64  `json:"provider_latency_ms,omitempty"`
}
