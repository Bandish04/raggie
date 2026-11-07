// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"slices"
	"strings"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/store"
)

var skillIDPattern = regexp.MustCompile(
	`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$`,
)

var allowedAnswerStyles = map[string]bool{
	"corporate":   true,
	"short":       true,
	"instructive": true,
	"balanced":    true,
}

var (
	errInvalidChatPolicy = errors.New("invalid chat policy request")
	errChatPolicyDenied  = errors.New("chat policy denied")
)

// resolveChatPolicy removes all client authority over prompt/tool policy, then
// applies trusted workspace defaults and the currently-active skill snapshot.
func resolveChatPolicy(
	ctx context.Context,
	cfg config.Config,
	deps Deps,
	userID string,
	req *chatStreamRequest,
) error {
	resolver := deps.ChatPolicy
	if resolver == nil && deps.Store != nil {
		resolver = deps.Store
	}

	// In authenticated production mode these fields are server-owned. Clear them
	// even if a custom deployment forgot to wire a resolver.
	if deps.WSInfo != nil || resolver != nil {
		req.SystemPrompt = ""
		req.AllowTools = nil
	}

	if req.SkillID == "" && req.SkillVersion != 0 {
		return errInvalidChatPolicy
	}
	if req.SkillID != "" {
		if !skillIDPattern.MatchString(req.SkillID) || req.SkillVersion < 1 || userID == "" {
			return errChatPolicyDenied
		}
		if resolver == nil {
			return errChatPolicyDenied
		}
	}
	if resolver == nil {
		return validateClientPreferences(cfg, nil, req)
	}

	policy, err := resolver.ResolveChatPolicy(
		ctx,
		userID,
		req.WorkspaceID,
		req.SkillID,
		req.SkillVersion,
	)
	if err != nil {
		if req.SkillID != "" {
			return fmt.Errorf("%w: %v", errChatPolicyDenied, err)
		}
		return fmt.Errorf("resolve workspace chat policy: %w", err)
	}

	req.SystemPrompt = strings.TrimSpace(policy.WorkspaceSystemPrompt)
	req.Temperature = policy.WorkspaceTemperature
	req.AllowTools = nil
	req.resolvedSkill = policy.Skill

	if policy.Skill != nil {
		req.SystemPrompt = joinTrustedPrompts(req.SystemPrompt, policy.Skill.Instructions)
		req.AllowTools = append([]string(nil), policy.Skill.AllowedTools...)
		if policy.Skill.Model != "" {
			req.Model = policy.Skill.Model
		}
		if policy.Skill.AnswerStyle != "" {
			req.AnswerStyle = policy.Skill.AnswerStyle
		}
	}

	return validateClientPreferences(cfg, policy.AllowedModels, req)
}

func validateClientPreferences(
	cfg config.Config,
	allowedModels []string,
	req *chatStreamRequest,
) error {
	req.Model = strings.TrimSpace(req.Model)
	if req.Model != "" && len(allowedModels) > 0 && !slices.Contains(allowedModels, req.Model) {
		return errChatPolicyDenied
	}
	if req.Model == "" {
		req.Model = cfg.ChatModel
	}
	if !cfg.HasModel(req.Model) {
		return errChatPolicyDenied
	}
	req.resolvedProvider = cfg.ProviderForModel(req.Model)

	req.AnswerStyle = strings.ToLower(strings.TrimSpace(req.AnswerStyle))
	if req.AnswerStyle != "" && !allowedAnswerStyles[req.AnswerStyle] {
		return errInvalidChatPolicy
	}
	return nil
}

func joinTrustedPrompts(workspacePrompt, skillInstructions string) string {
	parts := make([]string, 0, 2)
	if workspacePrompt = strings.TrimSpace(workspacePrompt); workspacePrompt != "" {
		parts = append(parts, "WORKSPACE POLICY:\n"+workspacePrompt)
	}
	if skillInstructions = strings.TrimSpace(skillInstructions); skillInstructions != "" {
		parts = append(parts, "ACTIVE SKILL POLICY:\n"+skillInstructions)
	}
	return strings.Join(parts, "\n\n")
}

func requestMessageAudit(req chatStreamRequest) store.MessageAudit {
	audit := store.MessageAudit{
		ModelUsed:    req.Model,
		ProviderUsed: req.resolvedProvider,
	}
	if req.resolvedSkill != nil {
		audit.SkillID = req.resolvedSkill.ID
		audit.SkillVersion = req.resolvedSkill.Version
		audit.SkillPolicyHash = req.resolvedSkill.PolicyHash
	}
	return audit
}
