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

func TestParseStages(t *testing.T) {
	got, err := parseStages("10, 50,100")
	if err != nil || len(got) != 3 || got[2] != 100 {
		t.Fatalf("got %v, %v", got, err)
	}
	for _, bad := range []string{"10,10", "50,10", "0", "x", ""} {
		if _, err := parseStages(bad); err == nil {
			t.Errorf("%q must be rejected", bad)
		}
	}
}

// The fake edge sheds above 60 concurrent streams, so with stages 5,20,100
// the harness must find 20 as the sustainable maximum and stop at 100.
func TestDryRunFindsTheSheddingPoint(t *testing.T) {
	out := t.TempDir()
	var stdout bytes.Buffer
	args := []string{"-dry-run", "-out", out, "-stages", "5,20,100,200", "-stage-duration", "400ms",
		"-ramp", "50ms", "-cooldown", "10ms", "-seed-docs", "3"}
	if err := run(context.Background(), args, &stdout); err != nil {
		t.Fatalf("%v\n%s", err, stdout.String())
	}
	mds, _ := filepath.Glob(filepath.Join(out, "a5-sse-*.md"))
	if len(mds) != 1 {
		t.Fatalf("reports = %v", mds)
	}
	md, _ := os.ReadFile(mds[0])
	for _, want := range []string{
		"maximum sustainable concurrency on this machine: 20 streams",
		"The 50,000-stream A5 target was NOT demonstrated (highest stage tested: 100)",
		"busy",
	} {
		if !strings.Contains(string(md), want) {
			t.Fatalf("report lacks %q:\n%s", want, md)
		}
	}
	if strings.Contains(string(md), "| 200 |") {
		t.Fatal("the harness must stop after the first failing stage")
	}
}

func TestJudgeAndVerdict(t *testing.T) {
	s := stageResult{Requests: 100, OK: 100, SuccessRate: 1}
	s.TTFT.P95 = 3 * time.Second
	if ok, why := judge(s, 0.99, 2*time.Second); ok || !strings.Contains(why, "TTFT") {
		t.Fatalf("judge = %v %q", ok, why)
	}
	if got := verdict(body{Target: a5Target, MaxSustainable: 0, Highest: 10}); !strings.Contains(got, "no sustainable concurrency") {
		t.Fatalf("verdict = %q", got)
	}
	if got := verdict(body{Target: a5Target, MaxSustainable: 60000, Highest: 60000, Threshold: 0.99}); !strings.Contains(got, "meets the 50,000") {
		t.Fatalf("verdict = %q", got)
	}
}
