// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"io"
	"log/slog"
	"testing"
	"time"
)

func TestBackgroundJobsShedsWhenFullAndDrains(t *testing.T) {
	jobs := NewBackgroundJobs(1, time.Second, slog.New(slog.NewTextHandler(io.Discard, nil)))
	started := make(chan struct{})
	release := make(chan struct{})

	if !jobs.TryGo("first", func(context.Context) {
		close(started)
		<-release
	}) {
		t.Fatal("first job should be admitted")
	}
	<-started
	if jobs.TryGo("second", func(context.Context) {}) {
		t.Fatal("second job should be shed while the only slot is occupied")
	}
	active, dropped := jobs.Stats()
	if active != 1 || dropped != 1 {
		t.Fatalf("stats = active:%d dropped:%d, want 1/1", active, dropped)
	}

	close(release)
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	if err := jobs.Shutdown(ctx); err != nil {
		t.Fatal(err)
	}
	if jobs.TryGo("after-shutdown", func(context.Context) {}) {
		t.Fatal("jobs must reject work after shutdown")
	}
	_, dropped = jobs.Stats()
	if dropped != 2 {
		t.Fatalf("dropped = %d, want 2", dropped)
	}
}

func TestBackgroundJobsAppliesPerJobTimeout(t *testing.T) {
	jobs := NewBackgroundJobs(1, 20*time.Millisecond, slog.New(slog.NewTextHandler(io.Discard, nil)))
	finished := make(chan error, 1)
	if !jobs.TryGo("timeout", func(ctx context.Context) {
		<-ctx.Done()
		finished <- ctx.Err()
	}) {
		t.Fatal("job should be admitted")
	}

	select {
	case err := <-finished:
		if err != context.DeadlineExceeded {
			t.Fatalf("job context error = %v, want deadline exceeded", err)
		}
	case <-time.After(time.Second):
		t.Fatal("job did not receive its timeout")
	}

	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	if err := jobs.Shutdown(ctx); err != nil {
		t.Fatal(err)
	}
}
