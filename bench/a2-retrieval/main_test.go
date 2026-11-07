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

func TestDryRunWritesReport(t *testing.T) {
	out := t.TempDir()
	var stdout bytes.Buffer
	err := run(context.Background(), []string{"-dry-run", "-out", out, "-iterations", "12", "-warmup", "2", "-seed-docs", "5", "-warm-set", "4"}, &stdout)
	if err != nil {
		t.Fatalf("%v\n%s", err, stdout.String())
	}
	mds, _ := filepath.Glob(filepath.Join(out, "a2-retrieval-*.md"))
	csvs, _ := filepath.Glob(filepath.Join(out, "a2-retrieval-*.csv"))
	jsons, _ := filepath.Glob(filepath.Join(out, "a2-retrieval-*.json"))
	if len(mds) != 1 || len(csvs) != 1 || len(jsons) != 1 {
		t.Fatalf("artifacts: %v %v %v", mds, csvs, jsons)
	}
	md, _ := os.ReadFile(mds[0])
	for _, want := range []string{"DRY RUN", "## Pass: cache-cold", "## Pass: cache-warm", "12/12 turns completed (100.0%)", "A2 proxy (time to `sources`, cache-warm): p95"} {
		if !strings.Contains(string(md), want) {
			t.Fatalf("report lacks %q:\n%s", want, md)
		}
	}
	csv, _ := os.ReadFile(csvs[0])
	if lines := strings.Count(string(csv), "\n"); lines != 1+24 {
		t.Fatalf("csv rows = %d, want header + 24", lines)
	}
}

func TestVerdictWithoutSuccess(t *testing.T) {
	if got := verdict([]pass{{Name: "cache-warm"}}); !strings.Contains(got, "no successful turns") {
		t.Fatalf("verdict = %q", got)
	}
}
