// SPDX-License-Identifier: Apache-2.0

// Command a3-ingest measures how long a 50-page PDF takes to become searchable
// (acceptance gate A3: ≤ 10 s, clock starting at worker pickup).
//
// It generates a deterministic, text-heavy Turkish + English PDF, uploads it
// through the control plane, and polls the document until it is SUCCESS,
// splitting the time into upload, queue wait (PENDING → PROCESSING) and worker
// processing (PROCESSING → SUCCESS) as observed by polling, plus the
// server-side created_at → updated_at span. The worker does not expose a
// parse/chunk/embed/upsert breakdown, so that split is not reported.
//
//	cd bench && go run ./a3-ingest
//	cd bench && go run ./a3-ingest -generate-only /tmp/a3.pdf   # just the PDF
//	cd bench && go run ./a3-ingest -dry-run
package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/alicangunduz/raggie/bench/internal/fakestack"
	"github.com/alicangunduz/raggie/bench/internal/harness"
	"github.com/alicangunduz/raggie/bench/internal/pdfgen"
	"github.com/alicangunduz/raggie/bench/internal/stack"
	"github.com/alicangunduz/raggie/bench/internal/stackenv"
	"github.com/alicangunduz/raggie/bench/internal/stats"
)

const a3Target = 10 * time.Second

type pdfInfo struct {
	Pages  int
	Seed   uint64
	Bytes  int
	Chars  int
	SHA256 string
}

type runResult struct {
	Run           int
	Filename      string
	Status        string
	Error         string
	SawProcessing bool
	Upload        time.Duration
	Queue         time.Duration // upload answered → PROCESSING first seen
	Processing    time.Duration // PROCESSING first seen → terminal first seen
	Wall          time.Duration // upload sent → terminal first seen
	Server        time.Duration // created_at → updated_at
}

type body struct {
	Target     time.Duration
	Poll       time.Duration
	PDF        pdfInfo
	Runs       []runResult
	Succeeded  int
	Wall       stats.Summary
	Processing stats.Summary
	Server     stats.Summary
	Verdict    string
}

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	if err := run(ctx, os.Args[1:], os.Stdout); err != nil {
		fmt.Fprintln(os.Stderr, "a3-ingest:", err)
		os.Exit(1)
	}
}

func run(ctx context.Context, args []string, out io.Writer) error {
	fs := flag.NewFlagSet("a3-ingest", flag.ContinueOnError)
	var c harness.Common
	c.Bind(fs, 30*time.Minute)
	pages := fs.Int("pages", 50, "PDF page count")
	seed := fs.Uint64("seed", 2026, "PDF content seed (same seed → byte-identical file)")
	runs := fs.Int("runs", 3, "sequential uploads to measure")
	poll := fs.Duration("poll", 250*time.Millisecond, "document status poll interval (the queue/processing split resolution)")
	runTimeout := fs.Duration("run-timeout", 10*time.Minute, "give up on one document after this long")
	generateOnly := fs.String("generate-only", "", "write the PDF to this path and exit (no stack needed)")
	if err := fs.Parse(args); err != nil {
		return err
	}

	pdf := pdfgen.Generate(pdfgen.Options{Pages: *pages, Seed: *seed})
	sum := sha256.Sum256(pdf)
	info := pdfInfo{Pages: *pages, Seed: *seed, Bytes: len(pdf), SHA256: hex.EncodeToString(sum[:])}
	for _, p := range pdfgen.Pages(pdfgen.Options{Pages: *pages, Seed: *seed}) {
		info.Chars += utf8.RuneCountInString(strings.Join(p, "\n"))
	}
	if *generateOnly != "" {
		if err := os.WriteFile(*generateOnly, pdf, 0o600); err != nil {
			return err
		}
		fmt.Fprintf(out, "wrote %s: %d pages, %d bytes, %d characters, sha256 %s\n", *generateOnly, info.Pages, info.Bytes, info.Chars, info.SHA256)
		return nil
	}

	ctx, cancel := context.WithTimeout(ctx, c.Timeout)
	defer cancel()
	r, err := harness.Start(ctx, "a3-ingest", "A3 — 50-page PDF ingestion", &c,
		fakestack.Options{QueueDelay: 150 * time.Millisecond, ProcessingDelay: 900 * time.Millisecond}, 4)
	if err != nil {
		return err
	}
	defer r.Close()
	ws, created, err := r.Workspace(ctx, "bench a3")
	if err != nil {
		return err
	}

	b := body{Target: a3Target, Poll: *poll, PDF: info}
	runID := strconv.FormatInt(time.Now().Unix(), 36)
	var wall, processing, server []time.Duration
	for i := 1; i <= *runs; i++ {
		res := measure(ctx, r.Session, ws.ID, fmt.Sprintf("raggie-a3-%dp-%d-%s-run%d.pdf", *pages, *seed, runID, i), pdf, *poll, *runTimeout)
		res.Run = i
		b.Runs = append(b.Runs, res)
		fmt.Fprintf(out, "run %d: %s in %s (processing %s)\n", i, res.Status, res.Wall, res.Processing)
		if res.Status != stack.StatusSuccess {
			continue
		}
		b.Succeeded++
		wall = append(wall, res.Wall)
		server = append(server, res.Server)
		if res.SawProcessing {
			processing = append(processing, res.Processing)
		}
	}
	b.Wall, b.Processing, b.Server = stats.Summarize(wall), stats.Summarize(processing), stats.Summarize(server)
	b.Verdict = verdict(b)

	config := []stackenv.KV{
		harness.KV("pages", *pages), harness.KV("seed", *seed), harness.KV("runs", *runs),
		harness.KV("poll", *poll), harness.KV("run_timeout", *runTimeout), harness.KV("workspace_reused", !created),
	}
	notes := []string{
		fmt.Sprintf("Queue and processing are observed by polling every %s, so each carries up to ±%s of error; the server-side span (created_at → updated_at) is exact but includes the queue wait.", *poll, *poll),
		"The ingestion worker exposes no per-stage timing, so the parse / chunk / embed / upsert split cannot be reported; instrumenting the worker is required for it.",
		"Runs are sequential, each a fresh document with identical content, so the measurement excludes queue contention.",
	}
	csvRows := [][]string{{"run", "filename", "status", "upload_ms", "queue_ms", "processing_ms", "wall_ms", "server_ms", "saw_processing", "error"}}
	for _, x := range b.Runs {
		csvRows = append(csvRows, []string{strconv.Itoa(x.Run), x.Filename, x.Status, stats.Millis(x.Upload), stats.Millis(x.Queue),
			stats.Millis(x.Processing), stats.Millis(x.Wall), stats.Millis(x.Server), strconv.FormatBool(x.SawProcessing), x.Error})
	}
	art, err := r.Finish(b, config, notes, b.Runs, csvRows)
	if err != nil {
		return err
	}
	fmt.Fprintf(out, "%s\nwrote %s\n", b.Verdict, art.Markdown)
	return nil
}

func measure(ctx context.Context, s *stack.Session, workspaceID, filename string, pdf []byte, poll, timeout time.Duration) runResult {
	res := runResult{Filename: filename}
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	start := time.Now()
	doc, err := s.Upload(ctx, workspaceID, filename, pdf)
	res.Upload = time.Since(start)
	if err != nil {
		res.Status, res.Error = "UPLOAD_FAILED", err.Error()
		return res
	}
	uploaded := start.Add(res.Upload)
	var processingAt time.Time
	final, err := s.WaitDocuments(ctx, workspaceID, []string{doc.ID}, poll, func(d stack.Document, at time.Time) {
		switch {
		case d.Status == stack.StatusProcessing:
			processingAt = at
		case d.Terminal():
			res.Wall = at.Sub(start)
			if !processingAt.IsZero() {
				res.SawProcessing = true
				res.Queue = processingAt.Sub(uploaded)
				res.Processing = at.Sub(processingAt)
			}
		}
	})
	d := final[doc.ID]
	res.Status, res.Error = d.Status, d.ErrorMessage
	if err != nil {
		res.Status, res.Error = "TIMEOUT", err.Error()
		return res
	}
	res.Server = d.UpdatedAt.Sub(d.CreatedAt)
	return res
}

func verdict(b body) string {
	if b.Succeeded == 0 {
		return "A3: no document was ingested successfully — no verdict."
	}
	if b.Processing.N == 0 {
		return fmt.Sprintf("A3: end-to-end p50 %s s; processing was too fast to observe at a %s poll — no A3 split.",
			secs(b.Wall.P50), b.Poll)
	}
	state := "within"
	if b.Processing.P50 > a3Target {
		state = "over"
	}
	return fmt.Sprintf("A3: worker processing p50 %s s (max %s s) — %s the %d s target; end-to-end p50 %s s.",
		secs(b.Processing.P50), secs(b.Processing.Max), state, int(a3Target.Seconds()), secs(b.Wall.P50))
}

func secs(d time.Duration) string { return strconv.FormatFloat(d.Seconds(), 'f', 2, 64) }
