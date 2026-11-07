// SPDX-License-Identifier: Apache-2.0

package locale

import (
	"context"
	"testing"
)

func TestParse(t *testing.T) {
	cases := map[string]struct {
		want Locale
		ok   bool
	}{
		"en": {EN, true}, "tr": {TR, true}, "TR": {TR, true}, "tr-TR": {TR, true}, "en_US": {EN, true},
		" en-GB ": {EN, true}, "de": {"", false}, "": {"", false}, "*": {"", false}, "english": {"", false},
	}
	for in, tc := range cases {
		got, ok := Parse(in)
		if got != tc.want || ok != tc.ok {
			t.Errorf("Parse(%q) = %q,%v want %q,%v", in, got, ok, tc.want, tc.ok)
		}
	}
}

func TestFromAcceptLanguage(t *testing.T) {
	cases := map[string]struct {
		want Locale
		ok   bool
	}{
		"tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7": {TR, true},
		"en-US,en;q=0.9":                      {EN, true},
		"de-DE,de;q=0.9,tr;q=0.5,en;q=0.4":    {TR, true},  // first SUPPORTED by preference
		"en;q=0.2, tr;q=0.8":                  {TR, true},  // q-values, not order
		"tr;q=0":                              {"", false}, // q=0 means "not acceptable"
		"de, fr":                              {"", false},
		"":                                    {"", false},
		"*":                                   {"", false},
	}
	for in, tc := range cases {
		got, ok := FromAcceptLanguage(in)
		if got != tc.want || ok != tc.ok {
			t.Errorf("FromAcceptLanguage(%q) = %q,%v want %q,%v", in, got, ok, tc.want, tc.ok)
		}
	}
}

func TestResolvePriority(t *testing.T) {
	cases := []struct {
		name string
		in   Inputs
		def  Locale
		want Locale
	}{
		{"explicit wins", Inputs{Explicit: "en", UserPreference: "tr", AcceptLanguage: "tr"}, TR, EN},
		{"user preference next", Inputs{UserPreference: "tr", AcceptLanguage: "en"}, EN, TR},
		{"accept-language next", Inputs{AcceptLanguage: "tr-TR,tr;q=0.9"}, EN, TR},
		{"default last", Inputs{}, TR, TR},
		{"invalid values skipped", Inputs{Explicit: "xx", UserPreference: "de", AcceptLanguage: "fr"}, EN, EN},
	}
	for _, tc := range cases {
		if got := Resolve(tc.in, tc.def); got != tc.want {
			t.Errorf("%s: Resolve = %q want %q", tc.name, got, tc.want)
		}
	}
}

func TestPickFallsBackToEnglish(t *testing.T) {
	m := map[Locale]string{EN: "hello", TR: "merhaba"}
	if Pick(m, TR) != "merhaba" || Pick(m, EN) != "hello" || Pick(m, Locale("de")) != "hello" {
		t.Fatal("Pick must select the locale and fall back to English")
	}
}

func TestContextRoundTrip(t *testing.T) {
	ctx := WithContext(context.Background(), TR)
	if FromContext(ctx, EN) != TR || FromContext(context.Background(), EN) != EN {
		t.Fatal("context round trip failed")
	}
}
