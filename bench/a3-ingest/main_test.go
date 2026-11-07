// SPDX-License-Identifier: Apache-2.0

package main

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestGenerateOnlyNeedsNoStack(t *testing.T) {
	path := filepath.Join(t.TempDir(), "a3.pdf")
	var out bytes.Buffer
	if err := run(context.Background(), []string{"-generate-only", path, "-pages", "3"}, &out); err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(path) // #nosec G304 -- the test's own temp file
	if err != nil || !bytes.HasPrefix(b, []byte("%PDF-")) || !strings.Contains(out.String(), "3 pages") {
		t.Fatalf("pdf: %v, out %q", err, out.String())
	}
}

func TestDryRunSplitsQueueAndProcessing(t *testing.T) {
	out := t.TempDir()
	var stdout bytes.Buffer
	if err := run(context.Background(), []string{"-dry-run", "-out", out, "-runs", "2", "-poll", "20ms", "-pages", "5"}, &stdout); err != nil {
		t.Fatalf("%v\n%s", err, stdout.String())
	}
	mds, _ := filepath.Glob(filepath.Join(out, "a3-ingest-*.md"))
	if len(mds) != 1 {
		t.Fatalf("reports = %v", mds)
	}
	md, _ := os.ReadFile(mds[0])
	for _, want := range []string{"DRY RUN", "## Summary (2/2 runs succeeded)", "A3: worker processing p50", "| 1 | SUCCESS |"} {
		if !strings.Contains(string(md), want) {
			t.Fatalf("report lacks %q:\n%s", want, md)
		}
	}
}

func TestVerdict(t *testing.T) {
	if !strings.Contains(verdict(body{}), "no verdict") {
		t.Fatal("no successes")
	}
	b := body{Succeeded: 1, Poll: time.Second}
	b.Wall.N, b.Wall.P50 = 1, 3*time.Second
	if !strings.Contains(verdict(b), "too fast to observe") {
		t.Fatalf("verdict = %q", verdict(b))
	}
	b.Processing.N, b.Processing.P50, b.Processing.Max = 1, 12*time.Second, 12*time.Second
	if !strings.Contains(verdict(b), "over the 10 s target") {
		t.Fatalf("verdict = %q", verdict(b))
	}
}
