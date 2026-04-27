package protocol

import (
	"bytes"
	"encoding/json"
	"fmt"
)

const SupportedSchemaVersion = 1

var validKinds = map[string]struct{}{
	"command":   {},
	"event":     {},
	"result":    {},
	"error":     {},
	"heartbeat": {},
}

type Envelope struct {
	SchemaVersion int            `json:"schema_version"`
	Kind          string         `json:"kind"`
	Type          string         `json:"type"`
	RequestID     string         `json:"request_id"`
	TimestampMS   int64          `json:"timestamp_ms"`
	DeadlineMS    int64          `json:"deadline_ms"`
	Payload       map[string]any `json:"payload"`
}

func Decode(line []byte) (Envelope, error) {
	var envelope Envelope
	if err := json.Unmarshal(bytes.TrimSpace(line), &envelope); err != nil {
		return Envelope{}, fmt.Errorf("invalid JSON worker envelope: %w", err)
	}
	if err := validate(&envelope, false); err != nil {
		return Envelope{}, err
	}
	return envelope, nil
}

func Encode(envelope Envelope) ([]byte, error) {
	if envelope.SchemaVersion == 0 {
		envelope.SchemaVersion = SupportedSchemaVersion
	}
	if envelope.Payload == nil {
		envelope.Payload = map[string]any{}
	}
	if err := validate(&envelope, true); err != nil {
		return nil, err
	}
	encoded, err := json.Marshal(envelope)
	if err != nil {
		return nil, err
	}
	return append(encoded, '\n'), nil
}

func validate(envelope *Envelope, allowEncodeDefaults bool) error {
	if allowEncodeDefaults && envelope.SchemaVersion == 0 {
		envelope.SchemaVersion = SupportedSchemaVersion
	}
	if envelope.SchemaVersion != SupportedSchemaVersion {
		return fmt.Errorf(
			"unsupported worker schema_version %d; expected %d",
			envelope.SchemaVersion,
			SupportedSchemaVersion,
		)
	}
	if _, ok := validKinds[envelope.Kind]; !ok {
		return fmt.Errorf("invalid worker envelope kind %q", envelope.Kind)
	}
	if envelope.Type == "" {
		return fmt.Errorf("worker envelope type must be a non-empty string")
	}
	if envelope.TimestampMS < 0 {
		return fmt.Errorf("worker envelope timestamp_ms must be non-negative")
	}
	if envelope.DeadlineMS < 0 {
		return fmt.Errorf("worker envelope deadline_ms must be non-negative")
	}
	if envelope.Payload == nil {
		envelope.Payload = map[string]any{}
	}
	return nil
}
