// SPDX-License-Identifier: Apache-2.0

// Command a5-sse finds how many concurrent chat SSE streams the edge sustains
// on the test machine (acceptance gate A5 targets 50,000; this harness only
// ever reports what it measured).
//
// It runs escalating stages of N concurrent streams against the edge with the
// mock LLM (MOCKLLM_TOKEN_DELAY_MS sets the per-token pace): every stream loops
// chat turns for the stage duration after a ramp-up. A stage passes when at
// least -success-threshold of its turns complete and the time-to-first-token
// p95 stays within -ttft-budget; the highest passing stage before the first
// failure is the maximum sustainable concurrency. Edge memory/CPU come from
// `docker stats`; edge gauges from its internal /metrics listener when
// -metrics-url is reachable.
//
//	cd bench && go run ./a5-sse -stages 10,50,100,200,400
//	cd bench && go run ./a5-sse -dry-run
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/alicangunduz/raggie/bench/internal/dockerstats"
	"github.com/alicangunduz/raggie/bench/internal/fakestack"
	"github.com/alicangunduz/raggie/bench/internal/harness"
	"github.com/alicangunduz/raggie/bench/internal/promscrape"
	"github.com/alicangunduz/raggie/bench/internal/stack"
	"github.com/alicangunduz/raggie/bench/internal/stackenv"
	"github.com/alicangunduz/raggie/bench/internal/stats"
)

const a5Target = 50000

type stageResult struct {
	Concurrency   int
	Wall          time.Duration
	Requests      int
	OK            int
	SuccessRate   float64
	Throughput    float64 // completed turns per second
	TTFT          stats.Summary
	Meta          stats.Summary
	Outcomes      []harness.Outcome
	PeakClient    int64 // streams the client actually held open at once
	EdgeMem       uint64
	EdgeCPU       float64
	MemSamples    int
	ActivePeak    float64
	HasActive     bool
	Goroutines    float64
	HasGoroutines bool
	Pass          bool
	Reason        string
}

type body struct {
	Target         int
	TTFTBudget     time.Duration
	Threshold      float64
	Stages         []stageResult
	MaxSustainable int
	Highest        int
	Verdict        string
	TokenDelay     string
	ChatMaxConc    string
	RateLimit      string
	FileLimit      uint64
	Resources      string
}

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	if err := run(ctx, os.Args[1:], os.Stdout); err != nil {
		fmt.Fprintln(os.Stderr, "a5-sse:", err)
		os.Exit(1)
	}
}

func parseStages(s string) ([]int, error) {
	var out []int
	for _, f := range strings.Split(s, ",") {
		n, err := strconv.Atoi(strings.TrimSpace(f))
		if err != nil || n <= 0 {
			return nil, fmt.Errorf("bad stage %q", f)
		}
		if len(out) > 0 && n <= out[len(out)-1] {
			return nil, errors.New("stages must increase")
		}
		out = append(out, n)
	}
	return out, nil
}

func run(ctx context.Context, args []string, out io.Writer) error {
	fs := flag.NewFlagSet("a5-sse", flag.ContinueOnError)
	var c harness.Common
	var g harness.GoldenFlags
	g.Bind(fs)
	c.Bind(fs, 2*time.Hour)
	stagesFlag := fs.String("stages", "10,25,50,100,200,400", "comma-separated concurrent-stream counts, increasing")
	stageDur := fs.Duration("stage-duration", 30*time.Second, "steady-state time per stage (after the ramp)")
	ramp := fs.Duration("ramp", 5*time.Second, "time over which a stage's streams are opened")
	cooldown := fs.Duration("cooldown", 5*time.Second, "pause between stages")
	ttftBudget := fs.Duration("ttft-budget", 2*time.Second, "time-to-first-token p95 a passing stage must stay within")
	threshold := fs.Float64("success-threshold", 0.99, "fraction of turns a passing stage must complete")
	requestTimeout := fs.Duration("request-timeout", 60*time.Second, "deadline of one chat turn")
	keepGoing := fs.Bool("continue", false, "run every stage even after one fails")
	seedDocs := fs.Int("seed-docs", 10, "golden-corpus documents indexed into a fresh workspace")
	project := fs.String("compose-project", "raggie-e2e", "compose project of the stack (to find the edge container for docker stats)")
	container := fs.String("edge-container", "", "edge container id/name for docker stats (default: discover via -compose-project)")
	statsEvery := fs.Duration("docker-stats-interval", 2*time.Second, "edge docker stats sampling interval (0 disables sampling)")
	metricsURL := fs.String("metrics-url", "", "edge internal /metrics URL, if reachable from this host")
	metricsToken := fs.String("metrics-token", os.Getenv("RAGGIE_BENCH_METRICS_TOKEN"), "bearer for -metrics-url (METRICS_TOKEN)")
	if err := fs.Parse(args); err != nil {
		return err
	}
	stages, err := parseStages(*stagesFlag)
	if err != nil {
		return err
	}
	fileLimit, _ := harness.RaiseFileLimit()

	ctx, cancel := context.WithTimeout(ctx, c.Timeout)
	defer cancel()
	r, err := harness.Start(ctx, "a5-sse", "A5 — concurrent SSE chat streams", &c,
		fakestack.Options{RetrievalDelay: 5 * time.Millisecond, TokenDelay: 5 * time.Millisecond, MaxConcurrent: 60},
		stages[len(stages)-1])
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
	ws, created, err := r.Workspace(ctx, "bench a5")
	if err != nil {
		return err
	}
	if created {
		files, err := gs.CorpusFiles(corpusDir)
		if err != nil {
			return err
		}
		if _, err := r.UploadAndWait(ctx, ws.ID, files[:min(*seedDocs, len(files))], 4, time.Second); err != nil {
			return err
		}
	}

	b := body{
		Target: a5Target, TTFTBudget: *ttftBudget, Threshold: *threshold, FileLimit: fileLimit,
		TokenDelay:  r.StackSetting("MOCKLLM_TOKEN_DELAY_MS", "unknown"),
		ChatMaxConc: r.StackSetting("LLMAAS_CHAT_MAX_CONCURRENCY", "unknown"),
		RateLimit:   r.StackSetting("RATE_LIMIT_ENABLED", "unknown"),
	}
	var sampler *dockerstats.Sampler
	var notes []string
	if !c.DryRun && *statsEvery > 0 {
		id := *container
		if id == "" {
			id, err = dockerstats.FindComposeContainer(ctx, *project, "edge")
		}
		if err != nil {
			notes = append(notes, "Edge memory/CPU were not sampled: "+err.Error()+".")
		} else {
			sampler = dockerstats.NewSampler(id, *statsEvery)
			sampler.Start(ctx)
			b.Resources = fmt.Sprintf("docker stats of the edge container (%s samples; peak per stage)", *statsEvery)
		}
	}
	if b.Resources == "" {
		b.Resources = "not sampled"
	}
	if *metricsURL == "" {
		notes = append(notes, "Edge gauges (active streams, goroutines) were not scraped: the edge's /metrics listener is internal (METRICS_ADDR) and the image is distroless; pass -metrics-url when it is reachable.")
	}

	var csvRows [][]string
	csvRows = append(csvRows, []string{"stage", "worker", "turn", "status", "outcome", "meta_ms", "first_token_ms", "done_ms", "tokens"})
	allPassed := true
	for _, n := range stages {
		fmt.Fprintf(out, "stage %d streams: ramp %s + %s…\n", n, *ramp, *stageDur)
		if sampler != nil {
			sampler.StopAndReset()
		}
		res, rows := runStage(ctx, r.Session, ws.ID, questions, n, *ramp, *stageDur, *requestTimeout, *metricsURL, *metricsToken)
		csvRows = append(csvRows, rows...)
		if sampler != nil {
			p := sampler.StopAndReset()
			res.EdgeMem, res.EdgeCPU, res.MemSamples = p.MemBytes, p.CPUPercent, p.Samples
		}
		res.Pass, res.Reason = judge(res, *threshold, *ttftBudget)
		b.Stages = append(b.Stages, res)
		b.Highest = n
		fmt.Fprintf(out, "  %d/%d ok (%s), ttft p95 %s ms → %s\n", res.OK, res.Requests, pct(res.SuccessRate), stats.Millis(res.TTFT.P95), res.Reason)
		// The sustainable count is the last stage of an unbroken passing run.
		if !res.Pass {
			allPassed = false
		} else if allPassed {
			b.MaxSustainable = n
		}
		if errors.Is(ctx.Err(), context.Canceled) || (!res.Pass && !*keepGoing) {
			break
		}
		if res.OutcomeHas("rate_limited") {
			notes = append(notes, harness.ErrRateLimited.Error())
			break
		}
		select {
		case <-time.After(*cooldown):
		case <-ctx.Done():
		}
	}
	b.Verdict = verdict(b)

	config := []stackenv.KV{
		harness.KV("stages", *stagesFlag), harness.KV("stage_duration", *stageDur), harness.KV("ramp", *ramp),
		harness.KV("cooldown", *cooldown), harness.KV("ttft_budget", *ttftBudget), harness.KV("success_threshold", *threshold),
		harness.KV("request_timeout", *requestTimeout), harness.KV("continue", *keepGoing),
		harness.KV("seed_docs", *seedDocs), harness.KV("workspace_reused", !created), harness.KV("client_open_file_limit", fileLimit),
		harness.KV("docker_stats_interval", *statsEvery),
	}
	notes = append(notes,
		"Every turn is a full chat (retrieval, persistence, mock-LLM stream, chat.completed event), not an idle connection: the sustainable count depends on the mock token pace and LLMAAS_CHAT_MAX_CONCURRENCY (the edge sheds with 503 busy above it).",
		"The load generator runs on the same machine as the stack unless stated otherwise; the result is a lower bound for a dedicated server.",
	)
	art, err := r.Finish(b, config, notes, b.Stages, csvRows)
	if err != nil {
		return err
	}
	fmt.Fprintf(out, "%s\nwrote %s\n", b.Verdict, art.Markdown)
	return nil
}

// OutcomeHas reports whether any outcome class mentions code.
func (s stageResult) OutcomeHas(code string) bool {
	for _, o := range s.Outcomes {
		if strings.Contains(o.Name, code) {
			return true
		}
	}
	return false
}

func judge(s stageResult, threshold float64, budget time.Duration) (bool, string) {
	switch {
	case s.Requests == 0:
		return false, "no turns completed in time"
	case s.SuccessRate < threshold:
		return false, fmt.Sprintf("FAIL: success %s < %s", pct(s.SuccessRate), pct(threshold))
	case s.TTFT.P95 > budget:
		return false, fmt.Sprintf("FAIL: TTFT p95 %s ms > %s ms", stats.Millis(s.TTFT.P95), stats.Millis(budget))
	default:
		return true, "pass"
	}
}

func runStage(ctx context.Context, s *stack.Session, workspaceID string, questions []string, n int,
	ramp, steady, requestTimeout time.Duration, metricsURL, metricsToken string) (stageResult, [][]string) {
	start := time.Now()
	deadline := start.Add(ramp + steady)
	var (
		mu      sync.Mutex
		results []stack.ChatResult
		rows    [][]string
		open    atomic.Int64
		peak    atomic.Int64
		wg      sync.WaitGroup
	)
	res := stageResult{Concurrency: n}
	stopScrape := make(chan struct{})
	scrapeDone := make(chan struct{})
	go func() {
		defer close(scrapeDone)
		if metricsURL == "" {
			return
		}
		t := time.NewTicker(time.Second)
		defer t.Stop()
		for {
			if body, err := promscrape.Scrape(ctx, http.DefaultClient, metricsURL, metricsToken); err == nil {
				if v, ok := promscrape.Value(body, "raggie_edge_active_streams"); ok {
					res.HasActive, res.ActivePeak = true, max(res.ActivePeak, v)
				}
				if v, ok := promscrape.Value(body, "go_goroutines"); ok {
					res.HasGoroutines, res.Goroutines = true, max(res.Goroutines, v)
				}
			}
			select {
			case <-stopScrape:
				return
			case <-t.C:
			}
		}
	}()
	for w := 0; w < n; w++ {
		wg.Add(1)
		go func(w int) {
			defer wg.Done()
			delay := time.Duration(int64(ramp) * int64(w) / int64(n))
			select {
			case <-time.After(delay):
			case <-ctx.Done():
				return
			}
			for turn := 0; time.Now().Before(deadline) && ctx.Err() == nil; turn++ {
				cur := open.Add(1)
				for p := peak.Load(); cur > p && !peak.CompareAndSwap(p, cur); p = peak.Load() {
				}
				tctx, cancel := context.WithTimeout(ctx, requestTimeout)
				r := s.Chat(tctx, stack.ChatRequest{WorkspaceID: workspaceID, Message: questions[(w*7+turn)%len(questions)]})
				cancel()
				open.Add(-1)
				mu.Lock()
				results = append(results, r)
				rows = append(rows, []string{strconv.Itoa(n), strconv.Itoa(w), strconv.Itoa(turn), strconv.Itoa(r.Status), r.Outcome(),
					stats.Millis(r.Meta), stats.Millis(r.FirstToken), stats.Millis(r.Done), strconv.Itoa(r.Tokens)})
				mu.Unlock()
				if r.ErrorCode == "rate_limited" {
					return
				}
			}
		}(w)
	}
	wg.Wait()
	close(stopScrape)
	<-scrapeDone
	res.Wall = time.Since(start).Round(time.Millisecond)
	var ttft, meta []time.Duration
	for _, r := range results {
		if r.OK() {
			ttft = append(ttft, r.FirstToken)
			meta = append(meta, r.Meta)
		}
	}
	res.Requests, res.OK = len(results), harness.SuccessCount(results)
	res.SuccessRate = stats.Ratio(res.OK, res.Requests)
	res.Throughput = float64(res.OK) / res.Wall.Seconds()
	res.TTFT, res.Meta = stats.Summarize(ttft), stats.Summarize(meta)
	res.Outcomes = harness.Outcomes(results)
	res.PeakClient = peak.Load()
	return res, rows
}

func verdict(b body) string {
	measured := fmt.Sprintf("A5: maximum sustainable concurrency on this machine: %d streams (≥ %s turns completed, TTFT p95 ≤ %s ms).",
		b.MaxSustainable, pct(b.Threshold), stats.Millis(b.TTFTBudget))
	if b.MaxSustainable == 0 {
		measured = "A5: no stage met the pass criteria — no sustainable concurrency demonstrated."
	}
	if b.MaxSustainable >= b.Target {
		return measured + " This meets the 50,000-stream A5 target."
	}
	return measured + fmt.Sprintf(" The 50,000-stream A5 target was NOT demonstrated (highest stage tested: %d).", b.Highest)
}

func pct(f float64) string { return strconv.FormatFloat(f*100, 'f', 1, 64) + "%" }
