// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"runtime"
	"strconv"
	"strings"
	"time"
)

// processStart approximates process_start_time_seconds: the package is
// initialized during process start-up, well within a second of exec.
var processStart = time.Now()

// runtimeMetrics renders the standard Go runtime and process families with the
// names and types of the Prometheus Go/process collectors, so dashboards and the
// A5 benchmark read goroutines and RSS without a client-library dependency.
func runtimeMetrics() string {
	var ms runtime.MemStats
	runtime.ReadMemStats(&ms)

	var b strings.Builder
	metric := func(name, typ, help string, value float64) {
		b.WriteString("# HELP " + name + " " + help + "\n# TYPE " + name + " " + typ + "\n" +
			name + " " + strconv.FormatFloat(value, 'g', -1, 64) + "\n")
	}
	metric("go_goroutines", "gauge", "Number of goroutines that currently exist.", float64(runtime.NumGoroutine()))
	b.WriteString("# HELP go_info Information about the Go environment.\n# TYPE go_info gauge\n" +
		`go_info{version="` + runtime.Version() + `"} 1` + "\n")
	metric("go_memstats_alloc_bytes", "gauge", "Number of bytes allocated and still in use.", float64(ms.Alloc))
	metric("go_memstats_alloc_bytes_total", "counter", "Total number of bytes allocated, even if freed.", float64(ms.TotalAlloc))
	metric("go_memstats_sys_bytes", "gauge", "Number of bytes obtained from system.", float64(ms.Sys))
	metric("go_memstats_heap_alloc_bytes", "gauge", "Number of heap bytes allocated and still in use.", float64(ms.HeapAlloc))
	metric("go_memstats_heap_inuse_bytes", "gauge", "Number of heap bytes that are in use.", float64(ms.HeapInuse))
	metric("go_memstats_heap_idle_bytes", "gauge", "Number of heap bytes waiting to be used.", float64(ms.HeapIdle))
	metric("go_memstats_heap_released_bytes", "gauge", "Number of heap bytes released to OS.", float64(ms.HeapReleased))
	metric("go_memstats_heap_objects", "gauge", "Number of allocated objects.", float64(ms.HeapObjects))
	metric("go_memstats_stack_inuse_bytes", "gauge", "Number of bytes in use by the stack allocator.", float64(ms.StackInuse))
	metric("go_memstats_next_gc_bytes", "gauge", "Number of heap bytes when next garbage collection will take place.", float64(ms.NextGC))
	metric("go_memstats_last_gc_time_seconds", "gauge", "Number of seconds since 1970 of last garbage collection.", float64(ms.LastGC)/1e9)
	b.WriteString("# HELP go_gc_duration_seconds A summary of the pause duration of garbage collection cycles.\n" +
		"# TYPE go_gc_duration_seconds summary\n" +
		"go_gc_duration_seconds_sum " + strconv.FormatFloat(float64(ms.PauseTotalNs)/1e9, 'g', -1, 64) + "\n" +
		"go_gc_duration_seconds_count " + strconv.FormatUint(uint64(ms.NumGC), 10) + "\n")

	if cpu, ok := processCPUSeconds(); ok {
		metric("process_cpu_seconds_total", "counter", "Total user and system CPU time spent in seconds.", cpu)
	}
	if rss, ok := processResidentMemoryBytes(); ok {
		metric("process_resident_memory_bytes", "gauge", "Resident memory size in bytes.", float64(rss))
	}
	if fds, ok := processOpenFDs(); ok {
		metric("process_open_fds", "gauge", "Number of open file descriptors.", float64(fds))
	}
	if maxFDs, ok := processMaxFDs(); ok {
		metric("process_max_fds", "gauge", "Maximum number of open file descriptors.", float64(maxFDs))
	}
	metric("process_start_time_seconds", "gauge", "Start time of the process since unix epoch in seconds.",
		float64(processStart.UnixNano())/1e9)
	return b.String()
}

// parseStatmRSS returns the resident set size from /proc/<pid>/statm content:
// the second field, in pages.
func parseStatmRSS(raw []byte, pageSize int) (uint64, bool) {
	fields := strings.Fields(string(raw))
	if len(fields) < 2 || pageSize <= 0 {
		return 0, false
	}
	pages, err := strconv.ParseUint(fields[1], 10, 64)
	if err != nil {
		return 0, false
	}
	return pages * uint64(pageSize), true
}
