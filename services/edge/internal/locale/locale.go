// SPDX-License-Identifier: Apache-2.0

// Package locale selects the language of server-authored text: error
// messages, LLM prompt templates and short notes appended to answers. The
// supported set mirrors the web UI (en, tr). The model always answers in the
// language of the user's question; the locale only picks the template
// language and user-facing defaults.
package locale

import (
	"context"
	"sort"
	"strconv"
	"strings"
)

// Locale is a supported base language tag.
type Locale string

const (
	EN Locale = "en"
	TR Locale = "tr"
)

// Supported lists the locales with a full template/message set.
var Supported = []Locale{EN, TR}

// Parse maps a language tag ("tr", "tr-TR", "en_US", case-insensitive) to a
// supported Locale.
func Parse(s string) (Locale, bool) {
	s = strings.ToLower(strings.TrimSpace(s))
	if i := strings.IndexAny(s, "-_"); i >= 0 {
		s = s[:i]
	}
	for _, l := range Supported {
		if s == string(l) {
			return l, true
		}
	}
	return "", false
}

// FromAcceptLanguage returns the most preferred supported locale of an HTTP
// Accept-Language header, honouring q-values (q=0 means "not acceptable").
func FromAcceptLanguage(header string) (Locale, bool) {
	type candidate struct {
		loc   Locale
		q     float64
		order int
	}
	var cands []candidate
	for i, part := range strings.Split(header, ",") {
		fields := strings.Split(strings.TrimSpace(part), ";")
		loc, ok := Parse(fields[0])
		if !ok {
			continue
		}
		q := 1.0
		for _, f := range fields[1:] {
			if v, found := strings.CutPrefix(strings.TrimSpace(f), "q="); found {
				if parsed, err := strconv.ParseFloat(v, 64); err == nil {
					q = parsed
				}
			}
		}
		if q <= 0 {
			continue
		}
		cands = append(cands, candidate{loc, q, i})
	}
	if len(cands) == 0 {
		return "", false
	}
	sort.SliceStable(cands, func(a, b int) bool { return cands[a].q > cands[b].q })
	return cands[0].loc, true
}

// Inputs are the locale signals of one request, in priority order.
type Inputs struct {
	Explicit       string // request field (e.g. the web UI's active locale)
	UserPreference string // stored profile preference (users.locale)
	AcceptLanguage string // HTTP Accept-Language (widget visitors' browsers)
}

// Resolve picks the first valid signal: explicit field, then the stored user
// preference, then Accept-Language, then def.
func Resolve(in Inputs, def Locale) Locale {
	if l, ok := Parse(in.Explicit); ok {
		return l
	}
	if l, ok := Parse(in.UserPreference); ok {
		return l
	}
	if l, ok := FromAcceptLanguage(in.AcceptLanguage); ok {
		return l
	}
	return def
}

// Pick returns m[l], falling back to the English entry.
func Pick[T any](m map[Locale]T, l Locale) T {
	if v, ok := m[l]; ok {
		return v
	}
	return m[EN]
}

type ctxKey struct{}

// WithContext stores the request's resolved locale.
func WithContext(ctx context.Context, l Locale) context.Context {
	return context.WithValue(ctx, ctxKey{}, l)
}

// FromContext returns the stored locale, or def when none was set.
func FromContext(ctx context.Context, def Locale) Locale {
	if l, ok := ctx.Value(ctxKey{}).(Locale); ok && l != "" {
		return l
	}
	return def
}
