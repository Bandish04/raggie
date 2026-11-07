// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"github.com/alicangunduz/raggie/services/edge/internal/agent"
	"github.com/alicangunduz/raggie/services/edge/internal/store"
)

func withToolAudit(audit store.MessageAudit, execs []agent.ToolExecution) store.MessageAudit {
	if len(execs) == 0 {
		return audit
	}
	audit.ToolCalls = make([]store.ToolCallAudit, 0, len(execs))
	for _, e := range execs {
		audit.ToolCalls = append(audit.ToolCalls, store.ToolCallAudit{
			ID:          e.ID,
			Name:        e.Name,
			Kind:        e.Kind,
			OK:          e.OK,
			LatencyMS:   e.LatencyMS,
			Error:       e.Error,
			ArgsSHA256:  e.ArgsSHA256,
			ResultChars: e.ResultChars,
		})
	}
	return audit
}
