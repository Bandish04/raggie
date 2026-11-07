// SPDX-License-Identifier: Apache-2.0

package evalmetrics

import "testing"

func TestNormalize(t *testing.T) {
	for _, tc := range []struct{ in, lang, want string }{
		{"  18 İş Günü. [1]", "tr", "18 iş günü"},
		{"IŞIK", "tr", "ışık"},
		{"IŞIK", "en", "işik"}, // non-Turkish casing keeps dotted i
		{"3.400 TL", "tr", "3400 tl"},
		{"1,250,000 USD", "en", "1250000 usd"},
		{"3,5 saat", "tr", "3.5 saat"},
		{"€85!", "en", "85"},
		{"Elif   Kaya'dır.", "tr", "elif kaya dır"},
	} {
		if got := Normalize(tc.in, tc.lang); got != tc.want {
			t.Errorf("Normalize(%q, %s) = %q, want %q", tc.in, tc.lang, got, tc.want)
		}
	}
}

func TestAnswerMatching(t *testing.T) {
	answers := []string{"18 iş günü", "18 gün"}
	if !ExactMatch("18 İş Günü.", answers, "tr") {
		t.Fatal("exact match after normalization")
	}
	if ExactMatch("Yıllık izin 18 iş günüdür [1].", answers, "tr") {
		t.Fatal("a sentence is not an exact match")
	}
	if !ContainsMatch("Tam zamanlı çalışanlar yılda 18 gün izin alır [1].", answers, "tr") {
		t.Fatal("contains match on a variant")
	}
	if ContainsMatch("Toplam 180 gün", []string{"18 gün"}, "tr") {
		t.Fatal("contains must respect token boundaries (18 ≠ 180)")
	}
	if !ContainsMatch("The cap is 85 EUR per day.", []string{"€85"}, "en") {
		t.Fatal("currency symbol variant")
	}
	if !ContainsMatch("Fiyat 3400 TL/ay.", []string{"3.400 TL"}, "tr") {
		t.Fatal("thousands separator normalization")
	}
	if ContainsMatch("anything", nil, "en") || ExactMatch("", []string{""}, "en") {
		t.Fatal("no expected answers / empty answers never match")
	}
}

func TestAbstained(t *testing.T) {
	for _, s := range []string{
		"Yüklü belgelerde bu konuya dair bilgi bulamadım.",
		"Bu bilgi kaynaklarda bulunamadı.",
		"Dokümanlarda sözleşmeli çalışanlar için ebeveyn izni belirtilmemiş.",
		"The uploaded documents contain no information on this topic.",
		"I couldn't find this in the documents.",
		"This is not mentioned in the provided sources.",
	} {
		if !Abstained(s) {
			t.Errorf("not detected as abstention: %q", s)
		}
	}
	for _, s := range []string{"Yıllık izin 18 iş günüdür [1].", "The allowance is 85 EUR [1]."} {
		if Abstained(s) {
			t.Errorf("answer misread as abstention: %q", s)
		}
	}
}

func TestCompoundAnswerNeedsEveryPart(t *testing.T) {
	answers := []string{"Ece Polat; 30 Jun 2026", "Ece Polat; 30 Haziran 2026"}
	if !ContainsMatch("Sorumlu Ece Polat, son tarih 30 Haziran 2026 [2].", answers, "tr") {
		t.Fatal("every part of a variant present")
	}
	if ContainsMatch("Sorumlu Ece Polat.", answers, "tr") {
		t.Fatal("a compound answer with a missing part must not match")
	}
	if !ExactMatch("Ece Polat; 30 Jun 2026", answers, "en") {
		t.Fatal("exact compound")
	}
}

func TestNormalizeIsNFC(t *testing.T) {
	decomposed := "g\u0306u\u0308n" // "ğün" as base letters + combining marks
	if Normalize(decomposed, "tr") != Normalize("ğün", "tr") {
		t.Fatalf("NFC: %q vs %q", Normalize(decomposed, "tr"), Normalize("ğün", "tr"))
	}
	if !ContainsMatch("Toplam 18 g\u0306u\u0308n", []string{"18 ğün"}, "tr") {
		t.Fatal("decomposed answer must match")
	}
}

func TestSpecNumberFormats(t *testing.T) {
	for _, tc := range []struct{ answer, expected, lang string }{
		{"Tepe trafik 1650 RPS idi.", "1.650 RPS", "tr"},
		{"Payı %15.", "%15", "tr"},
		{"Uptime 99,9% olmalı.", "%99,9", "tr"},
		{"The value is 168.4.", "168.4", "en"},
		{"Fiyat 2.750 TL.", "2750", "tr"},
	} {
		if !ContainsMatch(tc.answer, []string{tc.expected}, tc.lang) {
			t.Errorf("%q should contain %q (%s): %q vs %q", tc.answer, tc.expected, tc.lang,
				Normalize(tc.answer, tc.lang), Normalize(tc.expected, tc.lang))
		}
	}
}
