package main

import (
	"context"
	"fmt"
	"os"
	"strings"

	"github.com/moustafattia/yoyopod-core/workers/voice/go/internal/provider"
	"github.com/moustafattia/yoyopod-core/workers/voice/go/internal/worker"
)

func main() {
	selected, err := selectedProvider()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	if err := worker.New(selected, os.Stdin, os.Stdout, os.Stderr).Run(context.Background()); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func selectedProvider() (provider.Provider, error) {
	configured := strings.ToLower(strings.TrimSpace(os.Getenv("YOYOPOD_VOICE_WORKER_PROVIDER")))
	switch configured {
	case "", "mock", "default":
		return provider.MockProvider{}, nil
	case "openai":
		return provider.NewOpenAIProviderFromEnv(), nil
	default:
		return nil, fmt.Errorf("unknown YOYOPOD_VOICE_WORKER_PROVIDER %q", configured)
	}
}
