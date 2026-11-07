// SPDX-License-Identifier: Apache-2.0

// Command eval measures RAG quality with the exact-answer golden set
// (examples/golden/golden.yaml): recall@k, hit@k and MRR@10 over the
// documents the edge retrieved and the citation-hit rate (the answer cites an
// expected document), all over the answerable items; with a real LLM
// (-llm real) also exact / contains answer match against the answer and its
// variants, and the correct-abstention rate on unanswerable items. Every
// metric is broken down by language and question type. -answer-metrics adds
// the eval worker's faithfulness / citation scores.
//
// It indexes the golden set's corpus into a fresh workspace (or reuses
// -workspace) and asks every selected question as a new conversation.
// Embedding provider and reranker are stack settings: run once per
// configuration to build the comparison matrix.
//
//	cd bench && go run ./eval
//	cd bench && go run ./eval -llm real -answer-metrics   # real LLM configured
//	cd bench && go run ./eval -dry-run                    # fixture + fake stack
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/alicangunduz/raggie/bench/internal/dockerstats"
	"github.com/alicangunduz/raggie/bench/internal/evalmetrics"
	"github.com/alicangunduz/raggie/bench/internal/fakestack"
	"github.com/alicangunduz/raggie/bench/internal/golden"
	"github.com/alicangunduz/raggie/bench/internal/harness"
	"github.com/alicangunduz/raggie/bench/internal/stack"
	"github.com/alicangunduz/raggie/bench/internal/stackenv"
)

type group struct {
	Name    string
	Summary evalmetrics.Summary
	Recall  []kv // ordered recall@k cells
	Hit     []kv
}

// subset is one breakdown dimension ("language", "type") with its groups.
type subset struct {
	Name   string
	Groups []group
}

type kv struct {
	K     int
	Value float64
}

type answerMetrics struct {
	Requested        int
	Evaluated        int
	Faithfulness     float64
	FaithfulnessN    int
	CitationValidity float64
	ValidityN        int
	CitationCoverage float64
	CoverageN        int
	Error            string
}

type body struct {
	LLM           string
	AnswerMetrics bool // answer match / abstention are meaningful (real LLM)
	Embeddings    string
	Rerank        string
	Golden        string
	Corpus        string
	Ingest        *harness.IngestSummary
	Asked         int
	Failed        int
	Ks            []int
	Overall       group
	Subsets       []subset
	Answers       *answerMetrics
}

type questionRow struct {
	ID         string   `json:"id"`
	Language   string   `json:"language"`
	Type       string   `json:"type"`
	Difficulty string   `json:"difficulty"`
	Answerable bool     `json:"answerable"`
	Expected   []string `json:"expected_documents"`
	Ranked     []string `json:"ranked"`
	Cited      []string `json:"cited"`
	RR         float64  `json:"reciprocal_rank"`
	Exact      bool     `json:"exact_match"`
	Contains   bool     `json:"contains_match"`
	Abstained  bool     `json:"abstained"`
	Outcome    string   `json:"outcome"`
	Answer     string   `json:"answer"`
	Message    string   `json:"message_id"`
}

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	if err := run(ctx, os.Args[1:], os.Stdout); err != nil {
		fmt.Fprintln(os.Stderr, "eval:", err)
		os.Exit(1)
	}
}

func parseKs(s string) ([]int, error) {
	var ks []int
	for _, f := range strings.Split(s, ",") {
		k, err := strconv.Atoi(strings.TrimSpace(f))
		if err != nil || k <= 0 {
			return nil, fmt.Errorf("bad k %q", f)
		}
		ks = append(ks, k)
	}
	return ks, nil
}

func run(ctx context.Context, args []string, out io.Writer) error {
	fs := flag.NewFlagSet("eval", flag.ContinueOnError)
	var c harness.Common
	var g harness.GoldenFlags
	g.Bind(fs)
	c.Bind(fs, 2*time.Hour)
	lang := fs.String("lang", "", "only questions in this language (tr|en; default both)")
	qtype := fs.String("type", "", "only this question type (e.g. multi-hop; default all)")
	limit := fs.Int("limit", 0, "ask at most this many questions (0 = all)")
	ksFlag := fs.String("k", "1,3,5,10", "recall@k / hit@k cutoffs")
	concurrency := fs.Int("concurrency", 2, "questions in flight")
	pace := fs.Duration("pace", 0, "minimum gap between question starts (for rate-limited stacks)")
	ingestConcurrency := fs.Int("ingest-concurrency", 4, "parallel corpus uploads")
	llm := fs.String("llm", "mock", "chat LLM behind the stack (mock|real) — recorded, not detected; answer-match metrics are reported only for real")
	answerMetricsFlag := fs.Bool("answer-metrics", false, "collect the eval worker's faithfulness/citation scores via the stack's postgres (docker exec psql)")
	evalWait := fs.Duration("eval-wait", 3*time.Minute, "how long to wait for the eval worker to score the answers")
	project := fs.String("compose-project", "raggie-e2e", "compose project of the stack (to reach postgres for -answer-metrics)")
	pgUser := fs.String("pg-user", "raggie", "postgres user for -answer-metrics")
	pgDB := fs.String("pg-db", "raggie", "postgres database for -answer-metrics")
	if err := fs.Parse(args); err != nil {
		return err
	}
	ks, err := parseKs(*ksFlag)
	if err != nil {
		return err
	}

	ctx, cancel := context.WithTimeout(ctx, c.Timeout)
	defer cancel()
	r, err := harness.Start(ctx, "eval", "RAG retrieval-quality eval", &c,
		fakestack.Options{RetrievalDelay: 2 * time.Millisecond, TopK: 12}, *concurrency)
	if err != nil {
		return err
	}
	defer r.Close()

	gs, corpusDir, err := r.LoadGolden(g)
	if err != nil {
		return err
	}
	items := gs.Filter(golden.Filter{Language: *lang, Type: *qtype, Limit: *limit})
	if len(items) == 0 {
		return errors.New("no golden questions match the filters")
	}
	b := body{
		LLM: *llm, AnswerMetrics: *llm == "real", Ks: ks, Golden: gs.Path, Corpus: corpusDir,
		Embeddings: r.StackSetting("EMBEDDINGS_PROVIDER", "unknown"),
		Rerank:     r.StackSetting("RERANK_ENABLED", "unknown"),
	}

	ws, created, err := r.Workspace(ctx, "bench eval")
	if err != nil {
		return err
	}
	if created {
		files, err := gs.CorpusFiles(corpusDir)
		if err != nil {
			return err
		}
		fmt.Fprintf(out, "indexing %d corpus documents into workspace %s…\n", len(files), ws.ID)
		ingest, err := r.UploadAndWait(ctx, ws.ID, files, *ingestConcurrency, 2*time.Second)
		if err != nil {
			return err
		}
		b.Ingest = &ingest
	}

	fmt.Fprintf(out, "asking %d questions…\n", len(items))
	results, err := harness.RunChats(ctx, len(items), *concurrency, *pace, func(ctx context.Context, i int) stack.ChatResult {
		return r.Session.Chat(ctx, stack.ChatRequest{WorkspaceID: ws.ID, Message: items[i].Question, Locale: items[i].Language})
	})
	if err != nil {
		return err
	}

	rows := make([]questionRow, len(items))
	all := make([]evalmetrics.QuestionResult, len(items))
	var messageIDs []string
	for i, it := range items {
		res := results[i]
		filenames := make([]string, len(res.SourceList))
		for j, src := range res.SourceList {
			filenames[j] = src.Filename
		}
		qr := evalmetrics.QuestionResult{
			Answerable: it.Answerable(), RequireAll: it.RequiresAllDocuments(), Lang: it.Language,
			Ranked:   evalmetrics.RankedDocuments(filenames),
			Expected: it.ExpectedDocuments,
			Cited:    evalmetrics.CitedDocuments(res.Answer, filenames),
			Answer:   res.Answer,
			Answers:  it.Answers(),
		}
		all[i] = qr // a failed turn stays in the denominators: it retrieved and answered nothing
		rows[i] = questionRow{
			ID: it.ID, Language: it.Language, Type: it.Type, Difficulty: string(it.Difficulty), Answerable: it.Answerable(),
			Expected: it.ExpectedDocuments, Ranked: qr.Ranked, Cited: qr.Cited,
			RR:        evalmetrics.ReciprocalRank(qr.Ranked, it.ExpectedDocuments, 10, it.RequiresAllDocuments()),
			Exact:     evalmetrics.ExactMatch(res.Answer, qr.Answers, it.Language),
			Contains:  evalmetrics.ContainsMatch(res.Answer, qr.Answers, it.Language),
			Abstained: evalmetrics.Abstained(res.Answer), Outcome: res.Outcome(), Answer: res.Answer, Message: res.MessageID,
		}
		if !res.OK() {
			b.Failed++
		} else if res.MessageID != "" {
			messageIDs = append(messageIDs, res.MessageID)
		}
	}
	b.Asked = len(items)
	b.Overall = makeGroup("all", all, ks)
	pick := func(keep func(golden.Item) bool) []evalmetrics.QuestionResult {
		var out []evalmetrics.QuestionResult
		for i, it := range items {
			if keep(it) {
				out = append(out, all[i])
			}
		}
		return out
	}
	byLang := subset{Name: "language"}
	for _, l := range []string{"tr", "en"} {
		if set := pick(func(it golden.Item) bool { return it.Language == l }); len(set) > 0 {
			byLang.Groups = append(byLang.Groups, makeGroup(l, set, ks))
		}
	}
	byType := subset{Name: "type"}
	for _, t := range golden.Types {
		if set := pick(func(it golden.Item) bool { return it.Type == t }); len(set) > 0 {
			byType.Groups = append(byType.Groups, makeGroup(t, set, ks))
		}
	}
	b.Subsets = []subset{byLang, byType}

	if *answerMetricsFlag && !c.DryRun {
		fmt.Fprintf(out, "waiting up to %s for the eval worker…\n", *evalWait)
		b.Answers = collectAnswerMetrics(ctx, *project, *pgUser, *pgDB, messageIDs, *evalWait)
	}

	config := []stackenv.KV{
		harness.KV("golden", gs.Path), harness.KV("corpus", corpusDir),
		harness.KV("lang", orAll(*lang)), harness.KV("type", orAll(*qtype)), harness.KV("limit", *limit),
		harness.KV("k", *ksFlag), harness.KV("concurrency", *concurrency), harness.KV("pace", *pace),
		harness.KV("llm", *llm), harness.KV("answer_metrics", *answerMetricsFlag), harness.KV("workspace_reused", !created),
	}
	notes := []string{
		"Retrieval relevance is per document: chunks are collapsed to their document (best rank kept). Per the golden spec a multi-hop question needs ALL expected documents (hit@k only when every one is in the top k, recall@k gives partial credit, MRR uses the rank completing the set); any other question is answered by ANY one of them (recall@k = hit@k). Retrieval and citation metrics cover answerable items only; a failed turn counts as retrieving nothing.",
		"Answer matching normalizes Unicode (NFC), case (Turkish-aware), punctuation, citation markers and number formatting (1.250 = 1,250 = 1250; a decimal comma reads as a dot). Exact = the whole answer equals the answer or a variant; contains = it occurs on token boundaries, and a compound answer (parts joined by \"; \") needs every part. Abstention is detected with a Turkish + English phrase list — a heuristic; spot-check the per-question CSV.",
	}
	if !b.AnswerMetrics {
		notes = append(notes, "Answer match and abstention are not reported: the mock LLM templates its answers from the retrieved sources (it always cites [1]/[2]), so the citation-hit rate here equals top-1/2 retrieval accuracy. Run with -llm real against a real model for answer-level metrics.")
	}
	if *answerMetricsFlag && c.DryRun {
		notes = append(notes, "-answer-metrics is skipped in a dry run (no eval worker).")
	}
	csvRows := [][]string{{"id", "language", "type", "difficulty", "answerable", "outcome", "expected_documents", "ranked_top10",
		"cited", "reciprocal_rank", "exact_match", "contains_match", "abstained"}}
	for _, x := range rows {
		csvRows = append(csvRows, []string{x.ID, x.Language, x.Type, x.Difficulty, strconv.FormatBool(x.Answerable), x.Outcome,
			strings.Join(x.Expected, ";"), strings.Join(x.Ranked[:min(10, len(x.Ranked))], ";"), strings.Join(x.Cited, ";"),
			strconv.FormatFloat(x.RR, 'f', 4, 64), strconv.FormatBool(x.Exact), strconv.FormatBool(x.Contains), strconv.FormatBool(x.Abstained)})
	}
	art, err := r.Finish(b, config, notes, rows, csvRows)
	if err != nil {
		return err
	}
	o := b.Overall.Summary
	fmt.Fprintf(out, "MRR@10 %.3f · recall@%d %.3f · citation hit %.3f (answerable n=%d)\nwrote %s\n",
		o.MRR10, ks[len(ks)-1], o.RecallAt[ks[len(ks)-1]], o.CitationHit, o.Answerable, art.Markdown)
	return nil
}

func makeGroup(name string, results []evalmetrics.QuestionResult, ks []int) group {
	s := evalmetrics.Aggregate(results, ks)
	g := group{Name: name, Summary: s}
	for _, k := range ks {
		g.Recall = append(g.Recall, kv{k, s.RecallAt[k]})
		g.Hit = append(g.Hit, kv{k, s.HitAt[k]})
	}
	return g
}

func orAll(s string) string {
	if s == "" {
		return "all"
	}
	return s
}

var uuidRE = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

// collectAnswerMetrics polls the stack's postgres (via docker exec psql) until
// the eval worker has scored every answer or wait elapses.
func collectAnswerMetrics(ctx context.Context, project, user, db string, ids []string, wait time.Duration) *answerMetrics {
	am := &answerMetrics{Requested: len(ids)}
	var quoted []string
	for _, id := range ids {
		if uuidRE.MatchString(id) { // ids are inlined into SQL: only canonical UUIDs pass
			quoted = append(quoted, "'"+id+"'")
		}
	}
	if len(quoted) == 0 {
		am.Error = "no answer message ids to look up"
		return am
	}
	pg, err := dockerstats.FindComposeContainer(ctx, project, "postgres")
	if err != nil {
		am.Error = err.Error()
		return am
	}
	query := "SELECT coalesce(faithfulness_score::text,''), coalesce(citation_validity_score::text,''), coalesce(citation_coverage_score::text,'')" +
		" FROM messages WHERE evaluated_at IS NOT NULL AND id IN (" + strings.Join(quoted, ",") + ")"
	deadline := time.Now().Add(wait)
	var lines []string
	for {
		cmd := exec.CommandContext(ctx, "docker", "exec", pg, "psql", "-U", user, "-d", db, "-At", "-F", ",", "-c", query) // #nosec G204 -- fixed command; ids validated as UUIDs
		outB, err := cmd.Output()
		if err != nil {
			am.Error = "psql: " + err.Error()
			return am
		}
		lines = strings.Fields(strings.TrimSpace(string(outB)))
		if len(lines) >= len(quoted) || time.Now().After(deadline) || ctx.Err() != nil {
			break
		}
		select {
		case <-time.After(5 * time.Second):
		case <-ctx.Done():
		}
	}
	am.Evaluated = len(lines)
	for _, l := range lines {
		cols := strings.Split(l, ",")
		add := func(i int, sum *float64, n *int) {
			if i < len(cols) {
				if v, err := strconv.ParseFloat(cols[i], 64); err == nil {
					*sum += v
					*n++
				}
			}
		}
		add(0, &am.Faithfulness, &am.FaithfulnessN)
		add(1, &am.CitationValidity, &am.ValidityN)
		add(2, &am.CitationCoverage, &am.CoverageN)
	}
	if am.FaithfulnessN > 0 {
		am.Faithfulness /= float64(am.FaithfulnessN)
	}
	if am.ValidityN > 0 {
		am.CitationValidity /= float64(am.ValidityN)
	}
	if am.CoverageN > 0 {
		am.CitationCoverage /= float64(am.CoverageN)
	}
	return am
}
