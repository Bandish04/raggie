// SPDX-License-Identifier: Apache-2.0

package llm

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"sort"
	"sync"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

var (
	ErrUnknownModel               = errors.New("chat model is not configured")
	ErrUnsupportedModelCapability = errors.New("chat model capability is not supported")
)

type modelRoute struct {
	profile  config.ModelProfile
	provider *ChatProvider
}

type providerSignature struct {
	baseURL               string
	apiKey                string
	maxConcurrency        int
	responseHeaderTimeout int
}

// ChatRouter maps canonical product model ids to provider-native ids. Providers
// are shared by provider id, so all models on one endpoint use one concurrency
// budget while a local GPU and managed API cannot starve each other.
type ChatRouter struct {
	defaultModel string
	routes       map[string]modelRoute
	providers    map[string]*ChatProvider
}

func NewChatRouter(profiles []config.ModelProfile, defaultModel string) (*ChatRouter, error) {
	router := &ChatRouter{
		defaultModel: defaultModel,
		routes:       make(map[string]modelRoute, len(profiles)),
		providers:    make(map[string]*ChatProvider),
	}
	signatures := make(map[string]providerSignature)
	for _, profile := range profiles {
		signature := providerSignature{
			baseURL:        profile.BaseURL,
			apiKey:         profile.APIKey,
			maxConcurrency: profile.MaxConcurrency,

			responseHeaderTimeout: profile.ResponseHeaderTimeoutSeconds,
		}
		if existing, ok := signatures[profile.Provider]; ok && existing != signature {
			return nil, fmt.Errorf("provider %q has conflicting route settings", profile.Provider)
		}
		signatures[profile.Provider] = signature
		provider := router.providers[profile.Provider]
		if provider == nil {
			provider = NewChatProvider(
				profile.BaseURL,
				profile.APIKey,
				profile.UpstreamModel,
				profile.MaxTokens,
				profile.MaxConcurrency,
			).WithResponseHeaderTimeout(time.Duration(profile.ResponseHeaderTimeoutSeconds) * time.Second)
			router.providers[profile.Provider] = provider
		}
		if _, exists := router.routes[profile.ID]; exists {
			return nil, fmt.Errorf("duplicate model route %q", profile.ID)
		}
		router.routes[profile.ID] = modelRoute{profile: profile, provider: provider}
	}
	if _, ok := router.routes[defaultModel]; !ok {
		return nil, fmt.Errorf("%w: default model %q", ErrUnknownModel, defaultModel)
	}
	return router, nil
}

func (r *ChatRouter) Stream(
	ctx context.Context,
	req ports.ChatRequest,
) (<-chan ports.ChatChunk, error) {
	model := req.Model
	if model == "" {
		model = r.defaultModel
	}
	route, ok := r.routes[model]
	if !ok {
		return nil, fmt.Errorf("%w: %s", ErrUnknownModel, model)
	}
	if len(req.Tools) > 0 && !route.profile.Supports(config.CapabilityTools) {
		return nil, fmt.Errorf(
			"%w: model %s lacks tools",
			ErrUnsupportedModelCapability,
			model,
		)
	}
	if containsImage(req.Messages) && !route.profile.Supports(config.CapabilityVision) {
		return nil, fmt.Errorf(
			"%w: model %s lacks vision",
			ErrUnsupportedModelCapability,
			model,
		)
	}
	if !route.profile.Supports(config.CapabilityReasoning) {
		req.ReasoningEffort = ""
	}
	req.Model = route.profile.UpstreamModel
	if req.MaxTokens == 0 {
		req.MaxTokens = route.profile.MaxTokens
	}
	return route.provider.Stream(ctx, req)
}

func containsImage(messages []ports.Message) bool {
	for _, message := range messages {
		for _, part := range message.Parts {
			if part.Type == "image_url" && part.ImageURL != nil {
				return true
			}
		}
	}
	return false
}

func (r *ChatRouter) ListModels(ctx context.Context) ([]string, error) {
	profiles, err := r.ListModelProfiles(ctx)
	if err != nil {
		return nil, err
	}
	ids := make([]string, 0, len(profiles))
	for _, profile := range profiles {
		if profile.Available {
			ids = append(ids, profile.ID)
		}
	}
	return ids, nil
}

func (r *ChatRouter) ListModelProfiles(ctx context.Context) ([]ports.ModelDescriptor, error) {
	type providerResult struct {
		id     string
		models []string
		err    error
	}
	results := make(chan providerResult, len(r.providers))
	var wg sync.WaitGroup
	for id, provider := range r.providers {
		wg.Add(1)
		go func(id string, provider *ChatProvider) {
			defer wg.Done()
			models, err := provider.ListModels(ctx)
			results <- providerResult{id: id, models: models, err: err}
		}(id, provider)
	}
	wg.Wait()
	close(results)

	available := make(map[string]map[string]bool, len(r.providers))
	successfulProviders := 0
	var failures []error
	for result := range results {
		if result.err != nil {
			failures = append(failures, fmt.Errorf("%s: %w", result.id, result.err))
			continue
		}
		successfulProviders++
		models := make(map[string]bool, len(result.models))
		for _, model := range result.models {
			models[model] = true
		}
		available[result.id] = models
	}
	profiles := make([]ports.ModelDescriptor, 0, len(r.routes))
	for _, route := range r.routes {
		profiles = append(profiles, ports.ModelDescriptor{
			ID:            route.profile.ID,
			Provider:      route.profile.Provider,
			UpstreamModel: route.profile.UpstreamModel,
			Capabilities:  slices.Clone(route.profile.Capabilities),
			Available:     available[route.profile.Provider][route.profile.UpstreamModel],
		})
	}
	sort.Slice(profiles, func(i, j int) bool {
		return profiles[i].ID < profiles[j].ID
	})
	// Discovery remains useful when every provider is down: callers can display
	// configured canonical ids as unavailable. Required readiness independently
	// verifies that the default provider/model is live.
	if successfulProviders == 0 && len(failures) > 0 {
		return profiles, nil
	}
	return profiles, nil
}

func (r *ChatRouter) Ready(ctx context.Context) error {
	route, ok := r.routes[r.defaultModel]
	if !ok {
		return fmt.Errorf("%w: default model %q", ErrUnknownModel, r.defaultModel)
	}
	return route.provider.ReadyModel(ctx, route.profile.UpstreamModel)
}

var (
	_ ports.ChatProvider       = (*ChatRouter)(nil)
	_ ports.ModelLister        = (*ChatRouter)(nil)
	_ ports.ModelProfileLister = (*ChatRouter)(nil)
)
