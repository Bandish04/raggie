// SPDX-License-Identifier: Apache-2.0

package dockerstats

import (
	"context"
	"errors"
	"testing"
	"time"
)

func TestParseStatsLine(t *testing.T) {
	for line, want := range map[string]Sample{
		"123.4MiB / 5.852GiB|12.34%": {MemBytes: 129394278, CPUPercent: 12.34},
		"1.5GiB / 5.852GiB|250.00%":  {MemBytes: 1610612736, CPUPercent: 250},
		"512kB / 2GB|0.00%":          {MemBytes: 512000, CPUPercent: 0},
		"900B / 2GB|1%":              {MemBytes: 900, CPUPercent: 1},
	} {
		got, err := parseStatsLine(line)
		if err != nil || got.MemBytes != want.MemBytes || got.CPUPercent != want.CPUPercent {
			t.Errorf("%q → %+v, %v; want %+v", line, got, err, want)
		}
	}
	if _, err := parseStatsLine("garbage"); err == nil {
		t.Fatal("garbage must fail")
	}
}

func TestSamplerTracksPeak(t *testing.T) {
	lines := []string{"100MiB / 1GiB|10%", "300MiB / 1GiB|90%", "200MiB / 1GiB|50%"}
	i := 0
	s := &Sampler{Container: "c", Interval: time.Millisecond, run: func(context.Context, ...string) (string, error) {
		if i >= len(lines) {
			return "", errors.New("gone")
		}
		i++
		return lines[i-1], nil
	}}
	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()
	s.Start(ctx)
	time.Sleep(50 * time.Millisecond)
	peak := s.StopAndReset()
	if peak.MemBytes != 300<<20 || peak.CPUPercent != 90 || peak.Samples != 3 {
		t.Fatalf("peak = %+v", peak)
	}
	if again := s.StopAndReset(); again.Samples != 0 {
		t.Fatalf("reset failed: %+v", again)
	}
}

func TestFindComposeContainer(t *testing.T) {
	var gotArgs []string
	id, err := findWith(context.Background(), func(_ context.Context, args ...string) (string, error) {
		gotArgs = args
		return "abc123\n", nil
	}, "raggie-e2e", "edge")
	if err != nil || id != "abc123" {
		t.Fatalf("id = %q, %v", id, err)
	}
	want := []string{"ps", "-q", "--filter", "label=com.docker.compose.project=raggie-e2e", "--filter", "label=com.docker.compose.service=edge"}
	for i := range want {
		if gotArgs[i] != want[i] {
			t.Fatalf("args = %v", gotArgs)
		}
	}
	if _, err := findWith(context.Background(), func(context.Context, ...string) (string, error) { return "", nil }, "p", "edge"); err == nil {
		t.Fatal("no container must be an error")
	}
}
