package worker

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"sync"
	"time"

	"github.com/moustafattia/yoyopod-core/workers/voice/go/internal/protocol"
	"github.com/moustafattia/yoyopod-core/workers/voice/go/internal/provider"
)

type Worker struct {
	provider provider.Provider
	in       io.Reader
	out      io.Writer
	errOut   io.Writer

	writeMu sync.Mutex
	mu      sync.Mutex
	active  *activeRequest
	wg      sync.WaitGroup
}

type activeRequest struct {
	requestID   string
	cancel      context.CancelFunc
	cancelAcked bool
}

func New(
	voiceProvider provider.Provider,
	in io.Reader,
	out io.Writer,
	errOut io.Writer,
) *Worker {
	return &Worker{
		provider: voiceProvider,
		in:       in,
		out:      out,
		errOut:   errOut,
	}
}

func (w *Worker) Run(ctx context.Context) error {
	if err := w.emit(protocol.Envelope{
		Kind: "event",
		Type: "voice.ready",
		Payload: map[string]any{
			"ready": true,
		},
	}); err != nil {
		return err
	}

	scanner := bufio.NewScanner(w.in)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for scanner.Scan() {
		select {
		case <-ctx.Done():
			w.cancelActive()
			w.wg.Wait()
			return ctx.Err()
		default:
		}

		envelope, err := protocol.Decode(scanner.Bytes())
		if err != nil {
			fmt.Fprintf(w.errOut, "protocol decode error: %v\n", err)
			continue
		}
		if envelope.Kind != "command" {
			w.emitError(envelope, "invalid_kind", "worker only accepts command envelopes", false)
			continue
		}
		if w.handleCommand(ctx, envelope) {
			break
		}
	}
	if err := scanner.Err(); err != nil {
		return err
	}
	w.wg.Wait()
	return nil
}

func (w *Worker) handleCommand(ctx context.Context, envelope protocol.Envelope) bool {
	switch envelope.Type {
	case "voice.health":
		w.handleHealth(ctx, envelope)
	case "voice.transcribe":
		w.startWork(ctx, envelope, w.handleTranscribe)
	case "voice.speak":
		w.startWork(ctx, envelope, w.handleSpeak)
	case "voice.ask":
		w.startWork(ctx, envelope, w.handleAsk)
	case "voice.cancel":
		w.handleCancel(envelope)
	case "voice.shutdown", "worker.stop":
		w.cancelActive()
		return true
	default:
		w.emitError(envelope, "unknown_command", "unknown voice worker command", false)
	}
	return false
}

func (w *Worker) handleHealth(parent context.Context, envelope protocol.Envelope) {
	ctx, cancel := contextWithDeadline(parent, envelope.DeadlineMS)
	defer cancel()
	result, err := w.provider.Health(ctx)
	if err != nil {
		if isContextCancelled(ctx, err) {
			w.emitCancelled(envelope.RequestID, "deadline_or_cancelled")
			return
		}
		w.emitError(envelope, "provider_error", err.Error(), true)
		return
	}
	w.emitResult(envelope, "voice.health.result", result)
}

func (w *Worker) startWork(
	parent context.Context,
	envelope protocol.Envelope,
	handler func(context.Context, protocol.Envelope),
) {
	ctx, cancel := contextWithDeadline(parent, envelope.DeadlineMS)
	if !w.setActive(envelope.RequestID, cancel) {
		cancel()
		w.emitError(envelope, "busy", "voice worker is already processing a request", true)
		return
	}

	w.wg.Add(1)
	go func() {
		defer w.wg.Done()
		defer w.clearActive(envelope.RequestID)
		defer cancel()
		handler(ctx, envelope)
	}()
}

func (w *Worker) handleTranscribe(ctx context.Context, envelope protocol.Envelope) {
	var request provider.TranscribeRequest
	if err := decodePayload(envelope.Payload, &request); err != nil {
		w.emitError(envelope, "invalid_payload", err.Error(), false)
		return
	}
	result, err := w.provider.Transcribe(ctx, request)
	if err != nil || ctx.Err() != nil {
		if isContextCancelled(ctx, err) || ctx.Err() != nil {
			w.emitCancelled(envelope.RequestID, cancellationReason(ctx))
			return
		}
		if provider.IsInvalidPayload(err) {
			w.emitError(envelope, "invalid_payload", err.Error(), false)
			return
		}
		w.emitError(envelope, "provider_error", err.Error(), true)
		return
	}
	w.emitResult(envelope, "voice.transcribe.result", result)
}

func (w *Worker) handleSpeak(ctx context.Context, envelope protocol.Envelope) {
	var request provider.SpeakRequest
	if err := decodePayload(envelope.Payload, &request); err != nil {
		w.emitError(envelope, "invalid_payload", err.Error(), false)
		return
	}
	result, err := w.provider.Speak(ctx, request)
	if err != nil || ctx.Err() != nil {
		if isContextCancelled(ctx, err) || ctx.Err() != nil {
			w.emitCancelled(envelope.RequestID, cancellationReason(ctx))
			return
		}
		if provider.IsInvalidPayload(err) {
			w.emitError(envelope, "invalid_payload", err.Error(), false)
			return
		}
		w.emitError(envelope, "provider_error", err.Error(), true)
		return
	}
	w.emitResult(envelope, "voice.speak.result", result)
}

func (w *Worker) handleAsk(ctx context.Context, envelope protocol.Envelope) {
	var request provider.AskRequest
	if err := decodePayload(envelope.Payload, &request); err != nil {
		w.emitError(envelope, "invalid_payload", err.Error(), false)
		return
	}
	result, err := w.provider.Ask(ctx, request)
	if err != nil || ctx.Err() != nil {
		if isContextCancelled(ctx, err) || ctx.Err() != nil {
			w.emitCancelled(envelope.RequestID, cancellationReason(ctx))
			return
		}
		if provider.IsInvalidPayload(err) {
			w.emitError(envelope, "invalid_payload", err.Error(), false)
			return
		}
		w.emitError(envelope, "provider_error", err.Error(), true)
		return
	}
	w.emitResult(envelope, "voice.ask.result", result)
}

func (w *Worker) handleCancel(envelope protocol.Envelope) {
	targetID, _ := envelope.Payload["request_id"].(string)
	if targetID == "" {
		targetID = envelope.RequestID
	}
	if targetID == "" {
		w.emitError(envelope, "invalid_payload", "voice.cancel requires request_id", false)
		return
	}

	w.mu.Lock()
	active := w.active
	if active != nil && active.requestID == targetID {
		active.cancel()
		active.cancelAcked = true
		w.mu.Unlock()
		w.emitCancelAck(envelope, targetID, true, "cancel_requested")
		return
	}
	w.mu.Unlock()
	w.emitCancelAck(envelope, targetID, false, "not_active")
}

func (w *Worker) emitCancelAck(
	envelope protocol.Envelope,
	targetID string,
	cancelled bool,
	reason string,
) {
	replyID := envelope.RequestID
	if replyID == "" {
		replyID = targetID
	}
	w.emit(protocol.Envelope{
		Kind:      "result",
		Type:      "voice.cancelled",
		RequestID: replyID,
		Payload: map[string]any{
			"cancelled":         cancelled,
			"reason":            reason,
			"target_request_id": targetID,
		},
	})
}

func (w *Worker) setActive(requestID string, cancel context.CancelFunc) bool {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.active != nil {
		return false
	}
	w.active = &activeRequest{requestID: requestID, cancel: cancel}
	return true
}

func (w *Worker) clearActive(requestID string) {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.active != nil && w.active.requestID == requestID {
		w.active = nil
	}
}

func (w *Worker) cancelActive() {
	w.mu.Lock()
	active := w.active
	w.mu.Unlock()
	if active != nil {
		active.cancel()
	}
}

func (w *Worker) emitResult(envelope protocol.Envelope, resultType string, payload any) {
	w.emit(protocol.Envelope{
		Kind:      "result",
		Type:      resultType,
		RequestID: envelope.RequestID,
		Payload:   toPayload(payload),
	})
}

func (w *Worker) emitError(
	envelope protocol.Envelope,
	code string,
	message string,
	retryable bool,
) {
	w.emit(protocol.Envelope{
		Kind:      "error",
		Type:      "voice.error",
		RequestID: envelope.RequestID,
		Payload: map[string]any{
			"code":      code,
			"message":   message,
			"retryable": retryable,
		},
	})
}

func (w *Worker) emitCancelled(requestID string, reason string) {
	if w.cancelAlreadyAcked(requestID) {
		return
	}
	w.emit(protocol.Envelope{
		Kind:      "result",
		Type:      "voice.cancelled",
		RequestID: requestID,
		Payload: map[string]any{
			"cancelled": true,
			"reason":    reason,
		},
	})
}

func (w *Worker) cancelAlreadyAcked(requestID string) bool {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.active != nil && w.active.requestID == requestID && w.active.cancelAcked
}

func (w *Worker) emit(envelope protocol.Envelope) error {
	encoded, err := protocol.Encode(envelope)
	if err != nil {
		fmt.Fprintf(w.errOut, "protocol encode error: %v\n", err)
		return err
	}
	w.writeMu.Lock()
	defer w.writeMu.Unlock()
	_, err = w.out.Write(encoded)
	return err
}

func contextWithDeadline(parent context.Context, deadlineMS int64) (context.Context, context.CancelFunc) {
	if deadlineMS <= 0 {
		return context.WithCancel(parent)
	}
	return context.WithTimeout(parent, time.Duration(deadlineMS)*time.Millisecond)
}

func decodePayload(payload map[string]any, target any) error {
	encoded, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	return json.Unmarshal(encoded, target)
}

func toPayload(value any) map[string]any {
	encoded, err := json.Marshal(value)
	if err != nil {
		return map[string]any{}
	}
	payload := map[string]any{}
	if err := json.Unmarshal(encoded, &payload); err != nil {
		return map[string]any{}
	}
	return payload
}

func isContextCancelled(ctx context.Context, err error) bool {
	return errors.Is(err, context.Canceled) ||
		errors.Is(err, context.DeadlineExceeded) ||
		errors.Is(ctx.Err(), context.Canceled) ||
		errors.Is(ctx.Err(), context.DeadlineExceeded)
}

func cancellationReason(ctx context.Context) string {
	if errors.Is(ctx.Err(), context.DeadlineExceeded) {
		return "deadline_exceeded"
	}
	return "cancelled"
}
