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
	if err := worker.New(selectedProvider(), os.Stdin, os.Stdout, os.Stderr).Run(context.Background()); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func selectedProvider() provider.Provider {
	if strings.EqualFold(os.Getenv("YOYOPOD_VOICE_WORKER_PROVIDER"), "openai") {
		return provider.NewOpenAIProviderFromEnv()
	}
	return provider.MockProvider{}
}
