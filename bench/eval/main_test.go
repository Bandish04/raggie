// SPDX-License-Identifier: Apache-2.0

package main

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestParseKs(t *testing.T) {
	if ks, err := parseKs("1, 5,10"); err != nil || len(ks) != 3 || ks[1] != 5 {
		t.Fatalf("ks = %v, %v", ks, err)
	}
	if _, err := parseKs("0"); err == nil {
		t.Fatal("k=0 must be rejected")
	}
}

func dryRun(t *testing.T, extra ...string) string {
	t.Helper()
	out := t.TempDir()
	var stdout bytes.Buffer
	if err := run(context.Background(), append([]string{"-dry-run", "-out", out}, extra...), &stdout); err != nil {
		t.Fatalf("%v\n%s", err, stdout.String())
	}
	mds, _ := filepath.Glob(filepath.Join(out, "eval-*.md"))
	csvs, _ := filepath.Glob(filepath.Join(out, "eval-*.csv"))
	if len(mds) != 1 || len(csvs) != 1 {
		t.Fatalf("artifacts: %v %v", mds, csvs)
	}
	md, _ := os.ReadFile(mds[0])
	csv, _ := os.ReadFile(csvs[0])
	return string(md) + "\n---CSV---\n" + string(csv)
}

// The dry run uses the bench/eval/testdata fixture (5 items: 4 answerable,
// 1 unanswerable, both languages, five types) against the fake stack.
func TestDryRunMockLLMReportsRetrievalOnly(t *testing.T) {
	got := dryRun(t, "-answer-metrics")
	for _, want := range []string{
		"DRY RUN", "Corpus indexed: 4/4 documents",
		"| `mock` | `unknown` | `unknown` | 5 | 4 | 1 | 0 |",
		"| all | 4 |", "| tr | 3 |", "| en | 1 |",
		"| single-fact | 1 |", "| multi-hop | 1 |", "| negative/unanswerable | 0 | — |",
		"Not reported for this run (chat LLM `mock`)",
		"-answer-metrics is skipped in a dry run",
		"f-005,en,negative/unanswerable,medium,false,ok",
	} {
		if !strings.Contains(got, want) {
			t.Fatalf("report lacks %q:\n%s", want, got)
		}
	}
	if strings.Contains(got, "| exact match |") {
		t.Fatal("answer-match table must be hidden for the mock LLM")
	}
}

func TestDryRunRealLLMReportsAnswerMetrics(t *testing.T) {
	got := dryRun(t, "-llm", "real", "-lang", "tr")
	for _, want := range []string{"| exact match |", "| tr | 3 |", "correct abstention"} {
		if !strings.Contains(got, want) {
			t.Fatalf("report lacks %q:\n%s", want, got)
		}
	}
	if strings.Contains(got, "| en |") {
		t.Fatal("-lang tr must not evaluate English questions")
	}
}

func TestUUIDGuard(t *testing.T) {
	for _, bad := range []string{"x'); DROP TABLE messages;--", "", "123"} {
		if uuidRE.MatchString(bad) {
			t.Fatalf("%q must not pass the SQL guard", bad)
		}
	}
	if !uuidRE.MatchString("0a1b2c3d-0000-4000-8000-0123456789ab") {
		t.Fatal("canonical uuid rejected")
	}
}
