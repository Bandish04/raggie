// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"runtime"
	"strconv"
	"strings"
	"testing"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
)

// scrapeMetrics returns the internal listener's exposition.
func scrapeMetrics(t *testing.T) string {
	t.Helper()
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	srv := NewMetricsServer(config.Config{}, logger, Deps{})
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/metrics", nil))
	if rec.Code != http.StatusOK {
		t.Fatalf("GET /metrics: %d", rec.Code)
	}
	return rec.Body.String()
}

// parseExposition checks the text format (every sample belongs to a family
// declared once with # TYPE before it, values are floats) and returns the
// declared type and first unlabeled value per sample name.
func parseExposition(t *testing.T, body string) (types map[string]string, values map[string]float64) {
	t.Helper()
	types = map[string]string{}
	values = map[string]float64{}
	for _, line := range strings.Split(strings.TrimSuffix(body, "\n"), "\n") {
		if strings.HasPrefix(line, "# TYPE ") {
			f := strings.Fields(line)
			if len(f) != 4 {
				t.Fatalf("malformed TYPE line %q", line)
			}
			if _, dup := types[f[2]]; dup {
				t.Fatalf("family %s declared twice", f[2])
			}
			types[f[2]] = f[3]
			continue
		}
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		i := strings.LastIndexByte(line, ' ')
		if i < 0 {
			t.Fatalf("malformed sample %q", line)
		}
		name, raw := line[:i], line[i+1:]
		v, err := strconv.ParseFloat(raw, 64)
		if err != nil {
			t.Fatalf("sample %q: value %q is not a float", line, raw)
		}
		family := name
		if j := strings.IndexByte(family, '{'); j >= 0 {
			family = family[:j]
		}
		base := strings.TrimSuffix(strings.TrimSuffix(family, "_sum"), "_count")
		if _, ok := types[family]; !ok {
			if _, ok := types[base]; !ok {
				t.Fatalf("sample %q has no preceding # TYPE", line)
			}
		}
		if _, seen := values[name]; !seen {
			values[name] = v
		}
	}
	return types, values
}

func TestMetricsExposeGoRuntimeAndProcessMetrics(t *testing.T) {
	types, values := parseExposition(t, scrapeMetrics(t))

	want := map[string]string{
		"go_goroutines":                    "gauge",
		"go_info":                          "gauge",
		"go_memstats_alloc_bytes":          "gauge",
		"go_memstats_alloc_bytes_total":    "counter",
		"go_memstats_sys_bytes":            "gauge",
		"go_memstats_heap_alloc_bytes":     "gauge",
		"go_memstats_heap_inuse_bytes":     "gauge",
		"go_memstats_heap_idle_bytes":      "gauge",
		"go_memstats_heap_released_bytes":  "gauge",
		"go_memstats_heap_objects":         "gauge",
		"go_memstats_stack_inuse_bytes":    "gauge",
		"go_memstats_next_gc_bytes":        "gauge",
		"go_memstats_last_gc_time_seconds": "gauge",
		"go_gc_duration_seconds":           "summary",
		"process_cpu_seconds_total":        "counter",
		"process_start_time_seconds":       "gauge",
		"process_max_fds":                  "gauge",
	}
	if runtime.GOOS == "linux" {
		// Current RSS and open fds come from /proc (the Prometheus process
		// collector exposes them on Linux only as well).
		want["process_resident_memory_bytes"] = "gauge"
		want["process_open_fds"] = "gauge"
	}
	for name, typ := range want {
		if got := types[name]; got != typ {
			t.Errorf("%s: TYPE %q, want %q", name, got, typ)
		}
	}

	if v := values["go_goroutines"]; v < 1 {
		t.Errorf("go_goroutines = %v, want >= 1", v)
	}
	if v := values["go_memstats_sys_bytes"]; v <= 0 {
		t.Errorf("go_memstats_sys_bytes = %v, want > 0", v)
	}
	if v := values["process_cpu_seconds_total"]; v < 0 {
		t.Errorf("process_cpu_seconds_total = %v, want >= 0", v)
	}
	if v := values["process_start_time_seconds"]; v <= 0 {
		t.Errorf("process_start_time_seconds = %v, want a unix time", v)
	}
	if _, ok := values["go_gc_duration_seconds_count"]; !ok {
		t.Errorf("go_gc_duration_seconds_count missing")
	}
	if _, ok := values[`go_info{version="`+runtime.Version()+`"}`]; !ok {
		t.Errorf("go_info missing the runtime version label")
	}
	if runtime.GOOS == "linux" && values["process_resident_memory_bytes"] <= 0 {
		t.Errorf("process_resident_memory_bytes = %v, want > 0", values["process_resident_memory_bytes"])
	}
}

// The goroutine gauge is live, not a boot-time snapshot.
func TestMetricsGoroutinesTrackLiveCount(t *testing.T) {
	stop := make(chan struct{})
	const extra = 50
	for range extra {
		go func() { <-stop }()
	}
	defer close(stop)
	// The parked goroutines are certainly alive at the scrape; earlier ones
	// (e.g. a previous scrape's handlers) may exit at any time, so a delta
	// against an earlier sample is not a stable bound.
	_, after := parseExposition(t, scrapeMetrics(t))
	if after["go_goroutines"] < extra {
		t.Fatalf("go_goroutines %v with %d parked goroutines alive", after["go_goroutines"], extra)
	}
}

// The whole exposition (app + runtime families) stays well formed.
func TestMetricsExpositionWellFormed(t *testing.T) {
	types, _ := parseExposition(t, scrapeMetrics(t))
	if types["raggie_edge_up"] != "gauge" {
		t.Fatalf("raggie_edge_up missing from exposition")
	}
}

func TestParseStatmRSS(t *testing.T) {
	for _, tc := range []struct {
		raw  string
		page int
		want uint64
		ok   bool
	}{
		{"10560 2786 1560 1 0 1650 0\n", 4096, 2786 * 4096, true},
		{"10560 2786 1560 1 0 1650 0\n", 16384, 2786 * 16384, true},
		{"10560\n", 4096, 0, false},
		{"10560 x 1\n", 4096, 0, false},
		{"", 4096, 0, false},
		{"1 2", 0, 0, false},
	} {
		got, ok := parseStatmRSS([]byte(tc.raw), tc.page)
		if got != tc.want || ok != tc.ok {
			t.Errorf("parseStatmRSS(%q, %d) = %d, %v; want %d, %v", tc.raw, tc.page, got, ok, tc.want, tc.ok)
		}
	}
}
