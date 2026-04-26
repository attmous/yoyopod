package main

import (
	"testing"

	"github.com/moustafattia/yoyopod-core/workers/voice/go/internal/provider"
)

func TestSelectedProviderUsesOpenAIWhenConfigured(t *testing.T) {
	t.Setenv("YOYOPOD_VOICE_WORKER_PROVIDER", "openai")

	selected := selectedProvider()

	if _, ok := selected.(provider.OpenAIProvider); !ok {
		t.Fatalf("selected provider = %T, want provider.OpenAIProvider", selected)
	}
}

func TestSelectedProviderDefaultsToMock(t *testing.T) {
	t.Setenv("YOYOPOD_VOICE_WORKER_PROVIDER", "")

	selected := selectedProvider()

	if _, ok := selected.(provider.MockProvider); !ok {
		t.Fatalf("selected provider = %T, want provider.MockProvider", selected)
	}
}
