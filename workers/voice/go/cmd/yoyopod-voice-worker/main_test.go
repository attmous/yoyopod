package main

import (
	"testing"

	"github.com/moustafattia/yoyopod-core/workers/voice/go/internal/provider"
)

func TestSelectedProviderUsesOpenAIWhenConfigured(t *testing.T) {
	t.Setenv("YOYOPOD_VOICE_WORKER_PROVIDER", "openai")

	selected, err := selectedProvider()

	if err != nil {
		t.Fatalf("selectedProvider returned error: %v", err)
	}
	if _, ok := selected.(provider.OpenAIProvider); !ok {
		t.Fatalf("selected provider = %T, want provider.OpenAIProvider", selected)
	}
}

func TestSelectedProviderNormalizesConfiguredValue(t *testing.T) {
	t.Setenv("YOYOPOD_VOICE_WORKER_PROVIDER", " OPENAI ")

	selected, err := selectedProvider()

	if err != nil {
		t.Fatalf("selectedProvider returned error: %v", err)
	}
	if _, ok := selected.(provider.OpenAIProvider); !ok {
		t.Fatalf("selected provider = %T, want provider.OpenAIProvider", selected)
	}
}

func TestSelectedProviderDefaultsToMock(t *testing.T) {
	t.Setenv("YOYOPOD_VOICE_WORKER_PROVIDER", "")

	selected, err := selectedProvider()

	if err != nil {
		t.Fatalf("selectedProvider returned error: %v", err)
	}
	if _, ok := selected.(provider.MockProvider); !ok {
		t.Fatalf("selected provider = %T, want provider.MockProvider", selected)
	}
}

func TestSelectedProviderUsesMockWhenConfigured(t *testing.T) {
	t.Setenv("YOYOPOD_VOICE_WORKER_PROVIDER", "default")

	selected, err := selectedProvider()

	if err != nil {
		t.Fatalf("selectedProvider returned error: %v", err)
	}
	if _, ok := selected.(provider.MockProvider); !ok {
		t.Fatalf("selected provider = %T, want provider.MockProvider", selected)
	}
}

func TestSelectedProviderRejectsUnknownValue(t *testing.T) {
	t.Setenv("YOYOPOD_VOICE_WORKER_PROVIDER", "bogus")

	selected, err := selectedProvider()

	if err == nil {
		t.Fatalf("selectedProvider returned nil error for unknown provider")
	}
	if selected != nil {
		t.Fatalf("selected provider = %T, want nil", selected)
	}
}
