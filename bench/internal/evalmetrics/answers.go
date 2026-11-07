// SPDX-License-Identifier: Apache-2.0

package evalmetrics

import (
	"regexp"
	"strings"
	"unicode"

	"golang.org/x/text/unicode/norm"
)

var (
	citationMarker = regexp.MustCompile(`\[\d{1,3}\]`)
	thousandsSep   = regexp.MustCompile(`(\d)[.,](\d{3})\b`)
	decimalComma   = regexp.MustCompile(`(\d),(\d)`)
)

// Normalize prepares an answer for matching: Unicode NFC, citation markers removed,
// language-aware lowercasing (Turkish dotted/dotless i for "tr"), thousands
// separators dropped (1.250 / 1,250 → 1250), a decimal comma turned into a
// dot, every other non-alphanumeric rune turned into a space, whitespace
// collapsed. Known ambiguity: "3.400" always reads as three thousand four
// hundred, never 3.4.
func Normalize(s, lang string) string {
	s = citationMarker.ReplaceAllString(norm.NFC.String(s), " ")
	if lang == "tr" {
		s = strings.ToLowerSpecial(unicode.TurkishCase, s)
	} else {
		s = strings.ToLower(s)
	}
	for prev := ""; prev != s; {
		prev, s = s, thousandsSep.ReplaceAllString(s, "$1$2")
	}
	s = decimalComma.ReplaceAllString(s, "$1.$2")
	runes := []rune(s)
	var b strings.Builder
	for i, r := range runes {
		keepDot := r == '.' && i > 0 && i+1 < len(runes) && unicode.IsDigit(runes[i-1]) && unicode.IsDigit(runes[i+1])
		if unicode.IsLetter(r) || unicode.IsDigit(r) || keepDot {
			b.WriteRune(r)
		} else {
			b.WriteRune(' ')
		}
	}
	return strings.Join(strings.Fields(b.String()), " ")
}

// ExactMatch reports whether the whole normalized answer equals one of the
// normalized expected answers.
func ExactMatch(answer string, expected []string, lang string) bool {
	a := Normalize(answer, lang)
	if a == "" {
		return false
	}
	for _, e := range expected {
		if a == Normalize(e, lang) {
			return true
		}
	}
	return false
}

// ContainsMatch reports whether the answer contains one of the expected
// answers on token boundaries (so "18" never matches "180"). A compound
// expected answer joins its parts with "; " and matches only when every part
// is present.
func ContainsMatch(answer string, expected []string, lang string) bool {
	a := " " + Normalize(answer, lang) + " "
	for _, e := range expected {
		if containsAllParts(a, e, lang) {
			return true
		}
	}
	return false
}

func containsAllParts(normalizedAnswer, expected, lang string) bool {
	parts := 0
	for _, part := range strings.Split(expected, ";") {
		n := Normalize(part, lang)
		if n == "" {
			continue
		}
		if !strings.Contains(normalizedAnswer, " "+n+" ") {
			return false
		}
		parts++
	}
	return parts > 0
}

// abstentionPhrases are matched as substrings of the normalized answer (stems
// cover Turkish inflection). Heuristic: phrased to avoid firing on ordinary
// factual answers.
var abstentionPhrases = []string{
	// Turkish
	"bulamadım", "bulamadı", "bulunamadı", "bulunmuyor", "bilgi yok", "bilgim yok", "yer almıyor",
	"belirtilmemiş", "içermiyor", "bilmiyorum", "erişemiyorum",
	// English
	"not found", "no information", "does not contain", "doesn t contain", "do not contain", "don t contain",
	"not mentioned", "not specified", "could not find", "couldn t find", "cannot find", "can t find",
	"unable to find", "i don t know", "no relevant",
}

// Abstained reports whether the answer declines to answer (says the documents
// do not contain the information). A phrase-list heuristic, Turkish + English.
func Abstained(answer string) bool {
	// Both casings: Turkish lowercases "I don't" to "ı don t".
	tr, en := " "+Normalize(answer, "tr")+" ", " "+Normalize(answer, "en")+" "
	for _, p := range abstentionPhrases {
		if strings.Contains(tr, p) || strings.Contains(en, p) {
			return true
		}
	}
	return false
}
