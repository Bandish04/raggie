// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"errors"
	"slices"
	"testing"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/mcp"
	"github.com/alicangunduz/raggie/services/edge/internal/store"
)

type stubChatPolicyResolver struct {
	policy store.ChatPolicy
	err    error
}

func (s stubChatPolicyResolver) ResolveChatPolicy(
	context.Context,
	string,
	string,
	string,
	int,
) (store.ChatPolicy, error) {
	return s.policy, s.err
}

func TestResolveChatPolicyUsesTrustedSnapshot(t *testing.T) {
	resolved := &store.ResolvedSkill{
		ID:           "8e47f447-66ba-4d11-8c7a-f395b5352f90",
		Version:      3,
		PolicyHash:   "abc123",
		Instructions: "Only answer as the contract analyst.",
		Model:        "approved-model",
		AnswerStyle:  "corporate",
		AllowedTools: []string{"web_search"},
	}
	req := chatStreamRequest{
		WorkspaceID:  "ws-1",
		SystemPrompt: "malicious client prompt",
		Temperature:  1.9,
		Model:        "client-model",
		AnswerStyle:  "short",
		AllowTools:   []string{"mcp"},
		SkillID:      resolved.ID,
		SkillVersion: resolved.Version,
	}
	deps := Deps{ChatPolicy: stubChatPolicyResolver{policy: store.ChatPolicy{
		WorkspaceSystemPrompt: "Follow company policy.",
		WorkspaceTemperature:  0.2,
		AllowedModels:         []string{"approved-model"},
		Skill:                 resolved,
	}}}

	if err := resolveChatPolicy(context.Background(), config.Config{}, deps, "user-1", &req); err != nil {
		t.Fatal(err)
	}
	if req.Model != "approved-model" || req.AnswerStyle != "corporate" || req.Temperature != 0.2 {
		t.Fatalf("trusted policy was not applied: %+v", req)
	}
	if !slices.Equal(req.AllowTools, []string{"web_search"}) {
		t.Fatalf("client tool list leaked through: %v", req.AllowTools)
	}
	if req.SystemPrompt == "malicious client prompt" ||
		req.SystemPrompt != "WORKSPACE POLICY:\nFollow company policy.\n\nACTIVE SKILL POLICY:\nOnly answer as the contract analyst." {
		t.Fatalf("unexpected trusted prompt: %q", req.SystemPrompt)
	}
	audit := requestMessageAudit(req)
	if audit.SkillID != resolved.ID || audit.SkillVersion != 3 ||
		audit.SkillPolicyHash != "abc123" || audit.ModelUsed != "approved-model" {
		t.Fatalf("unexpected message audit: %+v", audit)
	}
}

func TestResolveChatPolicyRejectsUnavailableSkill(t *testing.T) {
	req := chatStreamRequest{
		WorkspaceID:  "ws-1",
		SkillID:      "8e47f447-66ba-4d11-8c7a-f395b5352f90",
		SkillVersion: 2,
	}
	err := resolveChatPolicy(
		context.Background(),
		config.Config{},
		Deps{ChatPolicy: stubChatPolicyResolver{err: errors.New("stale version")}},
		"user-1",
		&req,
	)
	if !errors.Is(err, errChatPolicyDenied) {
		t.Fatalf("expected policy denial, got %v", err)
	}
}

func TestResolveChatPolicyRejectsUnapprovedModel(t *testing.T) {
	req := chatStreamRequest{WorkspaceID: "ws-1", Model: "unapproved"}
	err := resolveChatPolicy(
		context.Background(),
		config.Config{},
		Deps{ChatPolicy: stubChatPolicyResolver{policy: store.ChatPolicy{
			AllowedModels: []string{"approved"},
		}}},
		"user-1",
		&req,
	)
	if !errors.Is(err, errChatPolicyDenied) {
		t.Fatalf("expected model policy denial, got %v", err)
	}
}

func TestResolveChatPolicyRejectsModelOutsideExplicitRuntimeRegistry(t *testing.T) {
	cfg := config.Config{
		ChatModel:             "local",
		ModelRegistryExplicit: true,
		ModelProfiles: []config.ModelProfile{{
			ID: "local", Provider: "ollama",
		}},
	}
	req := chatStreamRequest{WorkspaceID: "ws-1", Model: "managed"}
	err := resolveChatPolicy(
		context.Background(),
		cfg,
		Deps{ChatPolicy: stubChatPolicyResolver{policy: store.ChatPolicy{
			AllowedModels: []string{"local", "managed"},
		}}},
		"user-1",
		&req,
	)
	if !errors.Is(err, errChatPolicyDenied) {
		t.Fatalf("runtime registry must fail closed, got %v", err)
	}
}

func TestResolveChatPolicyAuditsCanonicalModelProvider(t *testing.T) {
	cfg := config.Config{
		ChatModel:             "local",
		ModelRegistryExplicit: true,
		ModelProfiles: []config.ModelProfile{{
			ID: "local", Provider: "ollama",
		}},
	}
	req := chatStreamRequest{WorkspaceID: "ws-1", Model: "local"}
	err := resolveChatPolicy(context.Background(), cfg, Deps{}, "user-1", &req)
	if err != nil {
		t.Fatal(err)
	}
	audit := requestMessageAudit(req)
	if audit.ModelUsed != "local" || audit.ProviderUsed != "ollama" {
		t.Fatalf("unexpected provider audit: %+v", audit)
	}
}

func TestMCPCategoryAllowsProviderCatalog(t *testing.T) {
	defs := filterAllowedMCPTools(
		[]mcp.ToolDef{{Name: "jira_search"}, {Name: "jira_get_issue"}},
		[]string{"mcp"},
		false,
	)
	if len(defs) != 2 {
		t.Fatalf("expected mcp category to allow the provider catalog, got %d", len(defs))
	}
}
