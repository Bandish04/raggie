// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"regexp"
	"time"
)

// Body caps for the small JSON endpoints. The chat body cap is configurable
// (CHAT_MAX_BODY_BYTES) because it carries vision attachments.
const (
	smallJSONBodyBytes = 16 << 10 // widget token, feedback
	// maxWorkspaceIDs bounds an "all workspaces" chat: each id costs one
	// authorization query and widens the vector filter.
	maxWorkspaceIDs = 200
)

var errBodyTooLarge = errors.New("request body too large")

// decodeJSONBody decodes one JSON value from a body capped at limit bytes.
// Exceeding the cap returns errBodyTooLarge (callers answer 413); any other
// failure is a plain decode error (400).
//
// The body must also arrive within HTTP_BODY_READ_TIMEOUT_SECONDS, so a client
// cannot hold a connection by trickling it. After a successful decode the read
// deadline is cleared: left on the connection it would later cancel the request
// context (net/http's background read) and cut an SSE stream. After a failed
// decode it stays, so net/http's drain of the unread body gives up too.
func decodeJSONBody(w http.ResponseWriter, r *http.Request, limit int64, v any) error {
	var rc *http.ResponseController
	if d, _ := r.Context().Value(bodyReadTimeoutKey{}).(time.Duration); d > 0 {
		if c := http.NewResponseController(w); c.SetReadDeadline(time.Now().Add(d)) == nil {
			rc = c
		}
	}
	err := json.NewDecoder(http.MaxBytesReader(w, r.Body, limit)).Decode(v)
	if err == nil && rc != nil {
		_ = rc.SetReadDeadline(time.Time{})
	}
	var tooLarge *http.MaxBytesError
	if errors.As(err, &tooLarge) {
		return errBodyTooLarge
	}
	return err
}

type bodyReadTimeoutKey struct{}

// withBodyReadTimeout hands the body read budget to decodeJSONBody.
func withBodyReadTimeout(d time.Duration) middleware {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), bodyReadTimeoutKey{}, d)))
		})
	}
}

// uuidLike reports whether s is a canonical textual UUID (client-supplied ids
// are validated before they reach a database cast).
func uuidLike(s string) bool { return uuidPattern.MatchString(s) }

var uuidPattern = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)
