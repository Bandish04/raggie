// SPDX-License-Identifier: Apache-2.0

// Command a2-retrieval measures end-to-end retrieval latency through the edge
// (acceptance gate A2: retrieval p95 < 200 ms).
//
// The edge has no retrieval-only endpoint, so the harness times real chat
// turns against the mock LLM: the edge embeds the query, runs the Qdrant hybrid
// search, reranks (when RERANK_ENABLED) and only then writes the SSE headers
// and the `sources` event. Time-to-`sources` is therefore an upper bound of
// A2 (it also includes persisting the user turn and opening the mock LLM
// stream); LLM generation time is excluded.
//
// Two measured passes follow a warm-up: cache-cold (every query unique, so the
// gateway's query-embedding cache cannot hit) and cache-warm (a small primed
// set repeated). Run once per configuration (local/cloud embeddings, rerank
// on/off) — the stack settings are recorded in the report.
//
//	cd bench && go run ./a2-retrieval            # against scripts/e2e-stack.sh
//	cd bench && go run ./a2-retrieval -dry-run   # validate the harness only
package main

import (
	"context"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strconv"
	"time"

	"github.com/alicangunduz/raggie/bench/internal/fakestack"
	"github.com/alicangunduz/raggie/bench/internal/harness"
	"github.com/alicangunduz/raggie/bench/internal/stack"
	"github.com/alicangunduz/raggie/bench/internal/stackenv"
	"github.com/alicangunduz/raggie/bench/internal/stats"
)

// a2Target is the acceptance gate.
const a2Target = 200 * time.Millisecond

type pass struct {
	Name        string
	Description string
	Requests    int
	OK          int
	SuccessRate float64
	Phases      []harness.Series
	Outcomes    []harness.Outcome
	A2          stats.Summary // time to `sources`
}

type body struct {
	Target     time.Duration
	Embeddings string
	Rerank     string
	Cache      string
	Seed       *harness.IngestSummary
	Passes     []pass
	Verdict    string
}

type sample struct {
	Pass         string  `json:"pass"`
	Index        int     `json:"index"`
	Status       int     `json:"status"`
	Outcome      string  `json:"outcome"`
	HeadersMS    float64 `json:"headers_ms"`
	MetaMS       float64 `json:"meta_ms"`
	SourcesMS    float64 `json:"sources_ms"`
	FirstTokenMS float64 `json:"first_token_ms"`
	DoneMS       float64 `json:"done_ms"`
	Sources      int     `json:"sources"`
}

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	if err := run(ctx, os.Args[1:], os.Stdout); err != nil {
		fmt.Fprintln(os.Stderr, "a2-retrieval:", err)
		os.Exit(1)
	}
}

func run(ctx context.Context, args []string, out io.Writer) error {
	fs := flag.NewFlagSet("a2-retrieval", flag.ContinueOnError)
	var c harness.Common
	var g harness.GoldenFlags
	g.Bind(fs)
	c.Bind(fs, 30*time.Minute)
	iterations := fs.Int("iterations", 200, "measured turns per pass")
	warmup := fs.Int("warmup", 20, "discarded warm-up turns")
	concurrency := fs.Int("concurrency", 1, "turns in flight (1 = pure latency)")
	pace := fs.Duration("pace", 0, "minimum gap between turn starts (for rate-limited stacks)")
	seedDocs := fs.Int("seed-docs", 30, "golden-corpus documents indexed into a fresh workspace")
	warmSet := fs.Int("warm-set", 20, "distinct queries repeated in the cache-warm pass")
	if err := fs.Parse(args); err != nil {
		return err
	}

	ctx, cancel := context.WithTimeout(ctx, c.Timeout)
	defer cancel()
	r, err := harness.Start(ctx, "a2-retrieval", "A2 — retrieval latency", &c,
		fakestack.Options{RetrievalDelay: 15 * time.Millisecond, TokenDelay: time.Millisecond}, *concurrency)
	if err != nil {
		return err
	}
	defer r.Close()

	gs, corpusDir, err := r.LoadGolden(g)
	if err != nil {
		return err
	}
	questions := harness.Questions(gs)
	if len(questions) == 0 {
		return fmt.Errorf("golden set %s has no questions", gs.Path)
	}

	b := body{
		Target:     a2Target,
		Embeddings: r.StackSetting("EMBEDDINGS_PROVIDER", "unknown"),
		Rerank:     r.StackSetting("RERANK_ENABLED", "unknown"),
		Cache:      r.StackSetting("EMBEDDINGS_CACHE_ENABLED", "unknown"),
	}
	ws, created, err := r.Workspace(ctx, "bench a2")
	if err != nil {
		return err
	}
	if created {
		files, err := gs.CorpusFiles(corpusDir)
		if err != nil {
			return err
		}
		files = files[:min(*seedDocs, len(files))]
		fmt.Fprintf(out, "seeding %d documents into workspace %s…\n", len(files), ws.ID)
		seed, err := r.UploadAndWait(ctx, ws.ID, files, 4, time.Second)
		if err != nil {
			return err
		}
		b.Seed = &seed
	}

	chat := func(msg string) stack.ChatResult {
		return r.Session.Chat(ctx, stack.ChatRequest{WorkspaceID: ws.ID, Message: msg})
	}
	fmt.Fprintf(out, "warm-up: %d turns…\n", *warmup)
	wu, err := harness.RunChats(ctx, *warmup, *concurrency, *pace, func(_ context.Context, i int) stack.ChatResult {
		return chat(questions[i%len(questions)])
	})
	if err != nil {
		return err
	}
	if *warmup > 0 && harness.SuccessCount(wu) == 0 {
		return fmt.Errorf("every warm-up turn failed (first: %s) — is the stack healthy?", wu[0].Outcome())
	}

	runID := strconv.FormatInt(time.Now().UnixNano()%1e6, 36)
	var samples []sample
	measure := func(name, desc string, query func(i int) string) error {
		fmt.Fprintf(out, "%s: %d turns…\n", name, *iterations)
		res, err := harness.RunChats(ctx, *iterations, *concurrency, *pace, func(_ context.Context, i int) stack.ChatResult {
			return chat(query(i))
		})
		if err != nil {
			return err
		}
		var a2 []time.Duration
		for i, x := range res {
			if x.OK() {
				a2 = append(a2, x.Sources)
			}
			samples = append(samples, sample{
				Pass: name, Index: i, Status: x.Status, Outcome: x.Outcome(),
				HeadersMS: ms(x.Headers), MetaMS: ms(x.Meta), SourcesMS: ms(x.Sources),
				FirstTokenMS: ms(x.FirstToken), DoneMS: ms(x.Done), Sources: len(x.SourceList),
			})
		}
		okN := harness.SuccessCount(res)
		b.Passes = append(b.Passes, pass{
			Name: name, Description: desc, Requests: len(res), OK: okN,
			SuccessRate: stats.Ratio(okN, len(res)), Phases: harness.PhaseSeries(res),
			Outcomes: harness.Outcomes(res), A2: stats.Summarize(a2),
		})
		return nil
	}

	if err := measure("cache-cold", "Every query is unique (a run-specific suffix), so the gateway's query-embedding cache cannot hit",
		func(i int) string { return fmt.Sprintf("%s (bench %s-%d)", questions[i%len(questions)], runID, i) }); err != nil {
		return err
	}
	warm := questions[:min(*warmSet, len(questions))]
	if _, err := harness.RunChats(ctx, len(warm), *concurrency, *pace, func(_ context.Context, i int) stack.ChatResult {
		return chat(warm[i])
	}); err != nil {
		return err
	}
	if err := measure("cache-warm", fmt.Sprintf("%d primed queries are repeated, so the query-embedding cache (when enabled) hits", len(warm)),
		func(i int) string { return warm[i%len(warm)] }); err != nil {
		return err
	}

	b.Verdict = verdict(b.Passes)
	config := []stackenv.KV{
		harness.KV("iterations", *iterations), harness.KV("warmup", *warmup), harness.KV("concurrency", *concurrency),
		harness.KV("pace", *pace), harness.KV("seed_docs", *seedDocs), harness.KV("warm_set", len(warm)),
		harness.KV("workspace_reused", !created), harness.KV("queries", fmt.Sprintf("%d golden questions from %s", len(questions), gs.Path)),
	}
	notes := []string{
		"Time-to-`sources` is an upper bound of A2: besides embed → hybrid search → rerank it includes persisting the user turn and opening the (mock) LLM stream. LLM generation is excluded.",
		"Rerank on/off and local/cloud embeddings are stack settings, not harness flags: run once per configuration and compare reports.",
	}
	if b.Cache == "unknown" || b.Cache == "false" {
		notes = append(notes, "The query-embedding cache is not known to be enabled, so the cache-warm pass may not differ from cache-cold.")
	}
	csvRows := [][]string{{"pass", "index", "status", "outcome", "headers_ms", "meta_ms", "sources_ms", "first_token_ms", "done_ms", "sources"}}
	for _, s := range samples {
		csvRows = append(csvRows, []string{s.Pass, strconv.Itoa(s.Index), strconv.Itoa(s.Status), s.Outcome,
			f3(s.HeadersMS), f3(s.MetaMS), f3(s.SourcesMS), f3(s.FirstTokenMS), f3(s.DoneMS), strconv.Itoa(s.Sources)})
	}
	art, err := r.Finish(b, config, notes, samples, csvRows)
	if err != nil {
		return err
	}
	fmt.Fprintf(out, "%s\nwrote %s\n", b.Verdict, art.Markdown)
	return nil
}

func verdict(passes []pass) string {
	for _, p := range passes {
		if p.Name == "cache-warm" {
			if p.A2.N == 0 {
				return "A2: no successful turns — no verdict."
			}
			state := "within"
			if p.A2.P95 > a2Target {
				state = "over"
			}
			return fmt.Sprintf("A2 proxy (time to `sources`, cache-warm): p95 %s ms — %s the %d ms target (upper bound).",
				stats.Millis(p.A2.P95), state, a2Target.Milliseconds())
		}
	}
	return "A2: no verdict."
}

func ms(d time.Duration) float64 { return float64(d) / float64(time.Millisecond) }

func f3(f float64) string { return strconv.FormatFloat(f, 'f', 3, 64) }
