// SPDX-License-Identifier: Apache-2.0

package pdfgen

import (
	"bytes"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"testing"
	"unicode/utf8"
)

func TestGenerateIsDeterministicAndPaged(t *testing.T) {
	a := Generate(Options{Pages: 50, Seed: 42})
	b := Generate(Options{Pages: 50, Seed: 42})
	if !bytes.Equal(a, b) {
		t.Fatal("same options must produce byte-identical PDFs")
	}
	if bytes.Equal(a, Generate(Options{Pages: 50, Seed: 43})) {
		t.Fatal("a different seed must change the content")
	}
	if !bytes.HasPrefix(a, []byte("%PDF-1.4")) || !bytes.HasSuffix(bytes.TrimSpace(a), []byte("%%EOF")) {
		t.Fatal("not a PDF")
	}
	if n := len(regexp.MustCompile(`/Type /Page\b[^s]`).FindAll(a, -1)); n != 50 {
		t.Fatalf("page objects = %d, want 50", n)
	}
	if !bytes.Contains(a, []byte("/Count 50")) {
		t.Fatal("page tree count")
	}
}

func TestXrefOffsetsPointAtObjects(t *testing.T) {
	pdf := Generate(Options{Pages: 3, Seed: 1})
	xref := bytes.LastIndex(pdf, []byte("\nxref\n"))
	m := regexp.MustCompile(`(?m)^(\d{10}) 00000 n\s*$`).FindAllSubmatch(pdf[xref:], -1)
	if len(m) == 0 {
		t.Fatal("no xref entries")
	}
	for i, e := range m {
		off, _ := strconv.Atoi(string(e[1]))
		if !bytes.HasPrefix(pdf[off:], []byte(strconv.Itoa(i+1)+" 0 obj")) {
			t.Fatalf("xref entry %d points at %q", i+1, pdf[off:min(off+12, len(pdf))])
		}
	}
	if !regexp.MustCompile(`startxref\n` + strconv.Itoa(xref+1) + `\n`).Match(pdf) {
		t.Fatal("startxref does not point at the xref table")
	}
}

func TestPagesAreTextHeavyBilingual(t *testing.T) {
	pages := Pages(Options{Pages: 50, Seed: 42})
	if len(pages) != 50 {
		t.Fatalf("pages = %d", len(pages))
	}
	var tr, en int
	for i, p := range pages {
		text := strings.Join(p, "\n")
		if n := utf8.RuneCountInString(text); n < 2500 {
			t.Fatalf("page %d has only %d characters", i+1, n)
		}
		if strings.ContainsAny(text, "ğşıİ") {
			tr++
		}
		if strings.Contains(text, " the ") {
			en++
		}
	}
	if tr != 50 || en != 50 {
		t.Fatalf("pages with Turkish/English text = %d/%d, want 50/50", tr, en)
	}
}

// When poppler's pdftotext is installed, the PDF must round-trip its Turkish
// text (exercises the custom encoding + ToUnicode map).
func TestTextExtractsWithPdftotext(t *testing.T) {
	bin, err := exec.LookPath("pdftotext")
	if err != nil {
		t.Skip("pdftotext not installed")
	}
	cmd := exec.Command(bin, "-f", "1", "-l", "1", "-", "-") // #nosec G204 -- pdftotext resolved via LookPath, fixed args
	cmd.Stdin = bytes.NewReader(Generate(Options{Pages: 2, Seed: 7}))
	out, err := cmd.Output()
	if err != nil {
		t.Fatal(err)
	}
	text := strings.Join(strings.Fields(string(out)), " ")
	first := strings.Join(strings.Fields(Pages(Options{Pages: 2, Seed: 7})[0][2]), " ")
	if !strings.Contains(text, first) {
		t.Fatalf("extracted text lacks line %q\n--- got ---\n%s", first, text[:min(600, len(text))])
	}
	for _, r := range []string{"ğ", "ş", "ı", "İ", "ç", "ö", "ü"} {
		if !strings.Contains(text, r) {
			t.Errorf("extracted text lacks %q", r)
		}
	}
}

// Every rune the generator writes must be encodable (no '?' fallback).
func TestEveryRuneIsEncodable(t *testing.T) {
	for _, page := range Pages(Options{Pages: 50, Seed: 42}) {
		for _, line := range page {
			for _, r := range line {
				if _, ok := codes[r]; !ok {
					t.Fatalf("rune %q in %q has no code", r, line)
				}
			}
		}
	}
}
