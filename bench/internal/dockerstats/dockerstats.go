// SPDX-License-Identifier: Apache-2.0

// Package dockerstats samples a container's memory and CPU via the docker CLI,
// for resource figures under load (the edge image is distroless, so its own
// metrics listener is usually not reachable from the host).
package dockerstats

import (
	"context"
	"errors"
	"fmt"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Sample is one reading.
type Sample struct {
	MemBytes   uint64
	CPUPercent float64 // 100 = one full core
}

// Peak is the maximum over a sampling window.
type Peak struct {
	MemBytes   uint64
	CPUPercent float64
	Samples    int
}

type runner func(ctx context.Context, args ...string) (string, error)

func dockerCLI(ctx context.Context, args ...string) (string, error) {
	out, err := exec.CommandContext(ctx, "docker", args...).Output() // #nosec G204 -- fixed docker subcommands
	return string(out), err
}

// FindComposeContainer returns the id of a compose service's container.
func FindComposeContainer(ctx context.Context, project, service string) (string, error) {
	return findWith(ctx, dockerCLI, project, service)
}

func findWith(ctx context.Context, run runner, project, service string) (string, error) {
	out, err := run(ctx, "ps", "-q", "--filter", "label=com.docker.compose.project="+project,
		"--filter", "label=com.docker.compose.service="+service)
	if err != nil {
		return "", err
	}
	ids := strings.Fields(out)
	if len(ids) == 0 {
		return "", fmt.Errorf("no running %s container in compose project %s", service, project)
	}
	return ids[0], nil
}

// Sampler polls `docker stats` in the background and keeps the peak.
type Sampler struct {
	Container string
	Interval  time.Duration
	run       runner

	mu   sync.Mutex
	peak Peak
	last error
}

// NewSampler samples container every interval once started.
func NewSampler(container string, interval time.Duration) *Sampler {
	return &Sampler{Container: container, Interval: interval, run: dockerCLI}
}

// Start samples until ctx ends.
func (s *Sampler) Start(ctx context.Context) {
	go func() {
		t := time.NewTicker(s.Interval)
		defer t.Stop()
		for {
			s.sample(ctx)
			select {
			case <-ctx.Done():
				return
			case <-t.C:
			}
		}
	}()
}

func (s *Sampler) sample(ctx context.Context) {
	out, err := s.run(ctx, "stats", "--no-stream", "--format", "{{.MemUsage}}|{{.CPUPerc}}", s.Container)
	var smp Sample
	if err == nil {
		smp, err = parseStatsLine(out)
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if err != nil {
		s.last = err
		return
	}
	s.peak.Samples++
	s.peak.MemBytes = max(s.peak.MemBytes, smp.MemBytes)
	s.peak.CPUPercent = max(s.peak.CPUPercent, smp.CPUPercent)
}

// StopAndReset returns the peak since the last call and starts a new window.
func (s *Sampler) StopAndReset() Peak {
	s.mu.Lock()
	defer s.mu.Unlock()
	p := s.peak
	s.peak = Peak{}
	return p
}

// LastError is the most recent sampling failure, if any.
func (s *Sampler) LastError() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.last
}

var units = map[string]float64{
	"B": 1, "KiB": 1 << 10, "MiB": 1 << 20, "GiB": 1 << 30, "TiB": 1 << 40,
	"kB": 1e3, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12,
}

func parseStatsLine(line string) (Sample, error) {
	mem, cpu, ok := strings.Cut(strings.TrimSpace(line), "|")
	if !ok {
		return Sample{}, errors.New("unexpected docker stats output: " + line)
	}
	used, _, _ := strings.Cut(mem, "/")
	used = strings.TrimSpace(used)
	i := strings.IndexFunc(used, func(r rune) bool { return (r < '0' || r > '9') && r != '.' })
	if i <= 0 {
		return Sample{}, errors.New("unexpected memory usage: " + used)
	}
	n, err := strconv.ParseFloat(used[:i], 64)
	mult, known := units[used[i:]]
	if err != nil || !known {
		return Sample{}, errors.New("unexpected memory usage: " + used)
	}
	pct, err := strconv.ParseFloat(strings.TrimSuffix(strings.TrimSpace(cpu), "%"), 64)
	if err != nil {
		return Sample{}, errors.New("unexpected cpu usage: " + cpu)
	}
	return Sample{MemBytes: uint64(n * mult), CPUPercent: pct}, nil
}
