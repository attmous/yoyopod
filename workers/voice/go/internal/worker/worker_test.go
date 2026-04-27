package worker_test

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/moustafattia/yoyopod-core/workers/voice/go/internal/protocol"
	"github.com/moustafattia/yoyopod-core/workers/voice/go/internal/provider"
	"github.com/moustafattia/yoyopod-core/workers/voice/go/internal/worker"
)

type blockingProvider struct {
	entered     chan struct{}
	release     chan struct{}
	enteredOnce bool
}

type ignoringCancelProvider struct {
	entered chan struct{}
	release chan struct{}
}

type invalidPayloadProvider struct{}

type recordingWriter struct {
	lines chan string
}

func newBlockingProvider() *blockingProvider {
	return &blockingProvider{
		entered: make(chan struct{}),
		release: make(chan struct{}),
	}
}

func (p *blockingProvider) Health(ctx context.Context) (provider.HealthResult, error) {
	select {
	case <-ctx.Done():
		return provider.HealthResult{}, ctx.Err()
	default:
		return provider.HealthResult{Healthy: true, Provider: "blocking"}, nil
	}
}

func (p *blockingProvider) Transcribe(ctx context.Context, request provider.TranscribeRequest) (provider.TranscribeResult, error) {
	p.markEntered()
	select {
	case <-ctx.Done():
		return provider.TranscribeResult{}, ctx.Err()
	case <-p.release:
		return provider.TranscribeResult{
			Text:       "released",
			Confidence: 1.0,
			IsFinal:    true,
		}, nil
	}
}

func (p *blockingProvider) Speak(ctx context.Context, request provider.SpeakRequest) (provider.SpeakResult, error) {
	p.markEntered()
	select {
	case <-ctx.Done():
		return provider.SpeakResult{}, ctx.Err()
	case <-p.release:
		return provider.SpeakResult{AudioPath: "/tmp/released.wav", Format: "wav", SampleRateHz: 16000}, nil
	}
}

func (p *blockingProvider) Ask(ctx context.Context, request provider.AskRequest) (provider.AskResult, error) {
	p.markEntered()
	select {
	case <-ctx.Done():
		return provider.AskResult{}, ctx.Err()
	case <-p.release:
		return provider.AskResult{Answer: "released", Model: "blocking"}, nil
	}
}

func (p *blockingProvider) markEntered() {
	if !p.enteredOnce {
		p.enteredOnce = true
		close(p.entered)
	}
}

func newIgnoringCancelProvider() *ignoringCancelProvider {
	return &ignoringCancelProvider{
		entered: make(chan struct{}),
		release: make(chan struct{}),
	}
}

func (p *ignoringCancelProvider) Health(ctx context.Context) (provider.HealthResult, error) {
	return provider.HealthResult{Healthy: true, Provider: "ignoring-cancel"}, nil
}

func (p *ignoringCancelProvider) Transcribe(ctx context.Context, request provider.TranscribeRequest) (provider.TranscribeResult, error) {
	close(p.entered)
	<-p.release
	return provider.TranscribeResult{
		Text:       "late release",
		Confidence: 1.0,
		IsFinal:    true,
	}, nil
}

func (p *ignoringCancelProvider) Speak(ctx context.Context, request provider.SpeakRequest) (provider.SpeakResult, error) {
	close(p.entered)
	<-p.release
	return provider.SpeakResult{AudioPath: "/tmp/late.wav", Format: "wav", SampleRateHz: 16000}, nil
}

func (p *ignoringCancelProvider) Ask(ctx context.Context, request provider.AskRequest) (provider.AskResult, error) {
	close(p.entered)
	<-p.release
	return provider.AskResult{Answer: "late release", Model: "ignoring-cancel"}, nil
}

func (p invalidPayloadProvider) Health(ctx context.Context) (provider.HealthResult, error) {
	return provider.HealthResult{Healthy: true, Provider: "invalid-payload"}, nil
}

func (p invalidPayloadProvider) Transcribe(ctx context.Context, request provider.TranscribeRequest) (provider.TranscribeResult, error) {
	return provider.TranscribeResult{}, provider.InvalidPayload("audio too long")
}

func (p invalidPayloadProvider) Speak(ctx context.Context, request provider.SpeakRequest) (provider.SpeakResult, error) {
	return provider.SpeakResult{}, provider.InvalidPayload("text too long")
}

func (p invalidPayloadProvider) Ask(ctx context.Context, request provider.AskRequest) (provider.AskResult, error) {
	return provider.AskResult{}, provider.InvalidPayload("question required")
}

func newRecordingWriter() *recordingWriter {
	return &recordingWriter{lines: make(chan string, 16)}
}

func (w *recordingWriter) Write(data []byte) (int, error) {
	for _, line := range strings.Split(string(data), "\n") {
		if strings.TrimSpace(line) != "" {
			w.lines <- line
		}
	}
	return len(data), nil
}

func TestMockProviderTranscribeUsesEnvironmentTranscript(t *testing.T) {
	t.Setenv("YOYOPOD_MOCK_TRANSCRIPT", "pause music")
	result, err := provider.MockProvider{}.Transcribe(
		context.Background(),
		provider.TranscribeRequest{AudioPath: "/tmp/input.wav"},
	)

	if err != nil {
		t.Fatalf("Transcribe returned error: %v", err)
	}
	if result.Text != "pause music" {
		t.Fatalf("Text = %q, want pause music", result.Text)
	}
	if !result.IsFinal {
		t.Fatalf("IsFinal = false, want true")
	}
}

func TestMockProviderSpeakWritesWAVFile(t *testing.T) {
	result, err := provider.MockProvider{}.Speak(
		context.Background(),
		provider.SpeakRequest{Text: "hello", SampleRateHz: 16000},
	)

	if err != nil {
		t.Fatalf("Speak returned error: %v", err)
	}
	t.Cleanup(func() { _ = os.Remove(result.AudioPath) })
	if result.Format != "wav" {
		t.Fatalf("Format = %q, want wav", result.Format)
	}
	if filepath.Ext(result.AudioPath) != ".wav" {
		t.Fatalf("AudioPath = %q, want .wav extension", result.AudioPath)
	}
	content, err := os.ReadFile(result.AudioPath)
	if err != nil {
		t.Fatalf("reading mock wav: %v", err)
	}
	if !bytes.HasPrefix(content, []byte("RIFF")) || !bytes.Contains(content, []byte("WAVE")) {
		t.Fatalf("mock speech file is not a deterministic wav header: %q", content)
	}
}

func TestWorkerAskCommandReturnsMockResult(t *testing.T) {
	t.Setenv("YOYOPOD_MOCK_ASK_ANSWER", "Sure, here is a tiny answer.")
	envelopes, stderr := runWorker(
		t,
		provider.MockProvider{},
		protocol.Envelope{
			Kind:      "command",
			Type:      "voice.ask",
			RequestID: "req-ask",
			Payload: map[string]any{
				"question": "What should I play?",
				"model":    "mock-ask",
				"history": []map[string]any{
					{"role": "user", "text": "hello"},
				},
			},
		},
	)

	if stderr != "" {
		t.Fatalf("stderr = %q, want empty", stderr)
	}
	result := findEnvelope(t, envelopes, "voice.ask.result")
	if result.RequestID != "req-ask" {
		t.Fatalf("RequestID = %q, want req-ask", result.RequestID)
	}
	if result.Payload["answer"] != "Sure, here is a tiny answer." {
		t.Fatalf("answer = %v, want mock env answer", result.Payload["answer"])
	}
	if result.Payload["model"] != "mock-ask" {
		t.Fatalf("model = %v, want mock-ask", result.Payload["model"])
	}
}

func TestWorkerAcceptsLargeCommandEnvelope(t *testing.T) {
	envelopes, stderr := runWorker(
		t,
		provider.MockProvider{},
		protocol.Envelope{
			Kind:      "command",
			Type:      "voice.ask",
			RequestID: "req-large",
			Payload: map[string]any{
				"question": strings.Repeat("hello ", 15000),
				"model":    "mock-large",
			},
		},
	)

	if stderr != "" {
		t.Fatalf("stderr = %q, want empty", stderr)
	}
	result := findEnvelope(t, envelopes, "voice.ask.result")
	if result.RequestID != "req-large" {
		t.Fatalf("RequestID = %q, want req-large", result.RequestID)
	}
}

func TestProtocolNormalizesNilPayloadAndEncodeDefaults(t *testing.T) {
	envelope, err := protocol.Decode([]byte(`{
		"schema_version": 1,
		"kind": "command",
		"type": "voice.health",
		"request_id": "req-health",
		"timestamp_ms": 1,
		"deadline_ms": 0,
		"payload": null
	}`))
	if err != nil {
		t.Fatalf("Decode returned error: %v", err)
	}
	if len(envelope.Payload) != 0 {
		t.Fatalf("Payload = %v, want empty map", envelope.Payload)
	}

	encoded, err := protocol.Encode(protocol.Envelope{
		Kind: "event",
		Type: "voice.ready",
	})
	if err != nil {
		t.Fatalf("Encode returned error: %v", err)
	}
	decoded, err := protocol.Decode(encoded)
	if err != nil {
		t.Fatalf("Decode encoded envelope returned error: %v", err)
	}
	if decoded.SchemaVersion != protocol.SupportedSchemaVersion {
		t.Fatalf("SchemaVersion = %d, want %d", decoded.SchemaVersion, protocol.SupportedSchemaVersion)
	}
	if decoded.Payload == nil {
		t.Fatalf("Payload is nil, want empty map")
	}
}

func TestWorkerReturnsUnknownCommandError(t *testing.T) {
	envelopes, stderr := runWorker(
		t,
		provider.MockProvider{},
		protocol.Envelope{
			Kind:      "command",
			Type:      "voice.unknown",
			RequestID: "req-unknown",
			Payload:   map[string]any{},
		},
	)

	errorEnvelope := findEnvelope(t, envelopes, "voice.error")
	if errorEnvelope.RequestID != "req-unknown" {
		t.Fatalf("RequestID = %q, want req-unknown", errorEnvelope.RequestID)
	}
	if errorEnvelope.Payload["code"] != "unknown_command" {
		t.Fatalf("code = %v, want unknown_command", errorEnvelope.Payload["code"])
	}
	if stderr != "" {
		t.Fatalf("stderr = %q, want empty", stderr)
	}
}

func TestWorkerRejectsConcurrentActiveWorkAsBusy(t *testing.T) {
	blocking := newBlockingProvider()
	input := strings.Join(
		[]string{
			mustEncode(t, protocol.Envelope{
				Kind:      "command",
				Type:      "voice.transcribe",
				RequestID: "req-active",
				DeadlineMS: 1000,
				Payload: map[string]any{
					"audio_path":     "/tmp/input.wav",
					"sample_rate_hz": float64(16000),
				},
			}),
			mustEncode(t, protocol.Envelope{
				Kind:      "command",
				Type:      "voice.speak",
				RequestID: "req-busy",
				DeadlineMS: 1000,
				Payload: map[string]any{
					"text":           "hello",
					"sample_rate_hz": float64(16000),
				},
			}),
		},
		"",
	)

	var stdout bytes.Buffer
	var stderr bytes.Buffer
	done := make(chan error, 1)
	go func() {
		done <- worker.New(blocking, strings.NewReader(input), &stdout, &stderr).Run(context.Background())
	}()

	waitFor(t, blocking.entered)
	close(blocking.release)
	if err := <-done; err != nil {
		t.Fatalf("Run returned error: %v", err)
	}
	envelopes := decodeOutput(t, stdout.String())
	errorEnvelope := findEnvelope(t, envelopes, "voice.error")
	if errorEnvelope.RequestID != "req-busy" {
		t.Fatalf("busy RequestID = %q, want req-busy", errorEnvelope.RequestID)
	}
	if errorEnvelope.Payload["code"] != "busy" {
		t.Fatalf("code = %v, want busy", errorEnvelope.Payload["code"])
	}
	if errorEnvelope.Payload["retryable"] != true {
		t.Fatalf("retryable = %v, want true", errorEnvelope.Payload["retryable"])
	}
	findEnvelope(t, envelopes, "voice.transcribe.result")
}

func TestWorkerMapsProviderInvalidPayloadToNonRetryableError(t *testing.T) {
	envelopes, _ := runWorker(
		t,
		invalidPayloadProvider{},
		protocol.Envelope{
			Kind:      "command",
			Type:      "voice.transcribe",
			RequestID: "req-invalid",
			Payload: map[string]any{
				"audio_path": "/tmp/input.wav",
			},
		},
	)

	errorEnvelope := findEnvelope(t, envelopes, "voice.error")
	if errorEnvelope.RequestID != "req-invalid" {
		t.Fatalf("RequestID = %q, want req-invalid", errorEnvelope.RequestID)
	}
	if errorEnvelope.Payload["code"] != "invalid_payload" {
		t.Fatalf("code = %v, want invalid_payload", errorEnvelope.Payload["code"])
	}
	if errorEnvelope.Payload["retryable"] != false {
		t.Fatalf("retryable = %v, want false", errorEnvelope.Payload["retryable"])
	}
}

func TestWorkerCancelEmitsCancelledResult(t *testing.T) {
	blocking := newBlockingProvider()
	input := strings.Join(
		[]string{
			mustEncode(t, protocol.Envelope{
				Kind:      "command",
				Type:      "voice.transcribe",
				RequestID: "req-active",
				DeadlineMS: 1000,
				Payload: map[string]any{
					"audio_path": "/tmp/input.wav",
				},
			}),
			mustEncode(t, protocol.Envelope{
				Kind:      "command",
				Type:      "voice.cancel",
				RequestID: "req-cancel",
				Payload: map[string]any{
					"request_id": "req-active",
				},
			}),
		},
		"",
	)

	envelopes, _ := runWorkerText(t, blocking, input)
	cancelled := findEnvelope(t, envelopes, "voice.cancelled")
	if cancelled.RequestID != "req-cancel" {
		t.Fatalf("cancelled RequestID = %q, want req-cancel", cancelled.RequestID)
	}
	if cancelled.Payload["cancelled"] != true {
		t.Fatalf("cancelled payload = %v, want true", cancelled.Payload["cancelled"])
	}
}

func TestWorkerCancelUsesCancelCommandRequestIDWhenTargetIsNotActive(t *testing.T) {
	envelopes, _ := runWorker(
		t,
		provider.MockProvider{},
		protocol.Envelope{
			Kind:      "command",
			Type:      "voice.cancel",
			RequestID: "req-cancel",
			Payload: map[string]any{
				"request_id": "req-missing",
			},
		},
	)

	cancelled := findEnvelope(t, envelopes, "voice.cancelled")
	if cancelled.RequestID != "req-cancel" {
		t.Fatalf("cancelled RequestID = %q, want req-cancel", cancelled.RequestID)
	}
	if cancelled.Payload["cancelled"] != false {
		t.Fatalf("cancelled payload = %v, want false", cancelled.Payload["cancelled"])
	}
}

func TestWorkerCancelEmitsImmediateAckWhenProviderIgnoresContext(t *testing.T) {
	voiceProvider := newIgnoringCancelProvider()
	stdinReader, stdinWriter := io.Pipe()
	stdout := newRecordingWriter()
	var stderr bytes.Buffer
	ctx, stop := context.WithCancel(context.Background())
	defer stop()
	done := make(chan error, 1)
	go func() {
		done <- worker.New(voiceProvider, stdinReader, stdout, &stderr).Run(ctx)
	}()

	first := mustEncode(t, protocol.Envelope{
		Kind:      "command",
		Type:      "voice.transcribe",
		RequestID: "req-active",
		DeadlineMS: 5000,
		Payload: map[string]any{
			"audio_path": "/tmp/input.wav",
		},
	})
	if _, err := stdinWriter.Write([]byte(first)); err != nil {
		t.Fatalf("writing transcribe command: %v", err)
	}
	waitFor(t, voiceProvider.entered)

	cancel := mustEncode(t, protocol.Envelope{
		Kind:      "command",
		Type:      "voice.cancel",
		RequestID: "req-cancel",
		Payload: map[string]any{
			"request_id": "req-active",
		},
	})
	if _, err := stdinWriter.Write([]byte(cancel)); err != nil {
		t.Fatalf("writing cancel command: %v", err)
	}

	cancelled := waitForEnvelope(t, stdout.lines, "voice.cancelled")
	if cancelled.RequestID != "req-cancel" {
		t.Fatalf("cancelled RequestID = %q, want req-cancel", cancelled.RequestID)
	}
	if cancelled.Payload["cancelled"] != true {
		t.Fatalf("cancelled payload = %v, want true", cancelled.Payload["cancelled"])
	}

	close(voiceProvider.release)
	if err := stdinWriter.Close(); err != nil {
		t.Fatalf("closing stdin writer: %v", err)
	}
	if err := <-done; err != nil {
		t.Fatalf("Run returned error: %v", err)
	}
}

func TestWorkerDeadlineEmitsCancelledResult(t *testing.T) {
	envelopes, _ := runWorker(
		t,
		newBlockingProvider(),
		protocol.Envelope{
			Kind:      "command",
			Type:      "voice.transcribe",
			RequestID: "req-expired",
			DeadlineMS: 1,
			Payload: map[string]any{
				"audio_path": "/tmp/input.wav",
			},
		},
	)

	cancelled := findEnvelope(t, envelopes, "voice.cancelled")
	if cancelled.RequestID != "req-expired" {
		t.Fatalf("cancelled RequestID = %q, want req-expired", cancelled.RequestID)
	}
}

func TestDecodeErrorsGoToStderrWithoutCrashing(t *testing.T) {
	envelopes, stderr := runWorkerText(t, provider.MockProvider{}, "{not-json}\n")

	findEnvelope(t, envelopes, "voice.ready")
	if !strings.Contains(stderr, "protocol decode error") {
		t.Fatalf("stderr = %q, want protocol decode error", stderr)
	}
}

func runWorker(t *testing.T, voiceProvider provider.Provider, command protocol.Envelope) ([]protocol.Envelope, string) {
	t.Helper()
	return runWorkerText(t, voiceProvider, mustEncode(t, command))
}

func runWorkerText(t *testing.T, voiceProvider provider.Provider, input string) ([]protocol.Envelope, string) {
	t.Helper()
	var stdout bytes.Buffer
	var stderr bytes.Buffer
	if err := worker.New(voiceProvider, strings.NewReader(input), &stdout, &stderr).Run(context.Background()); err != nil {
		t.Fatalf("Run returned error: %v", err)
	}
	return decodeOutput(t, stdout.String()), stderr.String()
}

func decodeOutput(t *testing.T, output string) []protocol.Envelope {
	t.Helper()
	var envelopes []protocol.Envelope
	scanner := bufio.NewScanner(strings.NewReader(output))
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		envelope, err := protocol.Decode([]byte(line))
		if err != nil {
			t.Fatalf("Decode(%q) returned error: %v", line, err)
		}
		envelopes = append(envelopes, envelope)
	}
	if err := scanner.Err(); err != nil {
		t.Fatalf("scanning output: %v", err)
	}
	return envelopes
}

func findEnvelope(t *testing.T, envelopes []protocol.Envelope, envelopeType string) protocol.Envelope {
	t.Helper()
	for _, envelope := range envelopes {
		if envelope.Type == envelopeType {
			return envelope
		}
	}
	payload, _ := json.Marshal(envelopes)
	t.Fatalf("missing envelope type %q in %s", envelopeType, payload)
	return protocol.Envelope{}
}

func mustEncode(t *testing.T, envelope protocol.Envelope) string {
	t.Helper()
	encoded, err := protocol.Encode(envelope)
	if err != nil {
		t.Fatalf("Encode returned error: %v", err)
	}
	return string(encoded)
}

func waitFor(t *testing.T, ch <-chan struct{}) {
	t.Helper()
	select {
	case <-ch:
	case <-time.After(time.Second):
		t.Fatalf("timed out waiting for channel")
	}
}

func waitForEnvelope(
	t *testing.T,
	lines <-chan string,
	envelopeType string,
) protocol.Envelope {
	t.Helper()
	timeout := time.After(time.Second)
	for {
		select {
		case line := <-lines:
			envelope, err := protocol.Decode([]byte(line))
			if err != nil {
				t.Fatalf("Decode(%q) returned error: %v", line, err)
			}
			if envelope.Type == envelopeType {
				return envelope
			}
		case <-timeout:
			t.Fatalf("timed out waiting for envelope type %q", envelopeType)
		}
	}
}

var _ provider.Provider = (*blockingProvider)(nil)
var _ provider.Provider = (*ignoringCancelProvider)(nil)
var _ provider.Provider = invalidPayloadProvider{}
