// SPDX-License-Identifier: Apache-2.0

package locale

import (
	"slices"
	"testing"
)

// Locale parsing of untrusted headers/fields: no panics and only supported
// locales ever come out.
func FuzzLocaleParsing(f *testing.F) {
	for _, s := range []string{"tr-TR,tr;q=0.9,en;q=0.8", "en;q=0", "*", "de-DE, tr;q=0.5", ";;;q=,", "TR_tr", "en;q=1e309"} {
		f.Add(s)
	}
	f.Fuzz(func(t *testing.T, s string) {
		if l, ok := Parse(s); ok != slices.Contains(Supported, l) {
			t.Fatalf("Parse(%q) = %q,%v", s, l, ok)
		}
		if l, ok := FromAcceptLanguage(s); ok != slices.Contains(Supported, l) {
			t.Fatalf("FromAcceptLanguage(%q) = %q,%v", s, l, ok)
		}
		if l := Resolve(Inputs{Explicit: s, UserPreference: s, AcceptLanguage: s}, EN); !slices.Contains(Supported, l) {
			t.Fatalf("Resolve returned unsupported %q", l)
		}
	})
}
