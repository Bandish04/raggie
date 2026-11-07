// SPDX-License-Identifier: Apache-2.0

// Package evalmetrics computes document-level retrieval-quality and answer
// metrics for the RAG eval harness. Relevance is judged per document
// (filename): the chunks the edge retrieved are collapsed to the documents
// they came from, in rank order, and compared with the expected documents
// under the golden set's rule (examples/golden/README.md): a multi-hop
// question needs ALL of them (requireAll), any other question is answered by
// ANY one of them.
package evalmetrics

import (
	"regexp"
	"strconv"
)

// RankedDocuments collapses per-chunk source filenames (best first) to unique
// documents, keeping the rank of each document's best chunk.
func RankedDocuments(chunkFilenames []string) []string {
	seen := make(map[string]bool, len(chunkFilenames))
	out := make([]string, 0, len(chunkFilenames))
	for _, f := range chunkFilenames {
		if f == "" || seen[f] {
			continue
		}
		seen[f] = true
		out = append(out, f)
	}
	return out
}

func set(xs []string) map[string]bool {
	m := make(map[string]bool, len(xs))
	for _, x := range xs {
		m[x] = true
	}
	return m
}

// RecallAtK is the retrieval recall within the top k. Under the any rule it
// is 1 when any expected document is there, else 0 (the documents are
// interchangeable sources); under the all rule it is the fraction of expected
// documents found (partial credit for a multi-hop chain).
func RecallAtK(ranked, expected []string, k int, requireAll bool) float64 {
	if len(expected) == 0 {
		return 0
	}
	want := set(expected)
	found := 0
	for i := 0; i < len(ranked) && i < k; i++ {
		if want[ranked[i]] {
			found++
		}
	}
	if !requireAll {
		return float64(min(found, 1))
	}
	return float64(found) / float64(len(want))
}

// HitAtK reports whether the top k satisfies the question: any expected
// document, or every one of them under the all rule.
func HitAtK(ranked, expected []string, k int, requireAll bool) bool {
	r := RecallAtK(ranked, expected, k, requireAll)
	if requireAll {
		return r == 1
	}
	return r > 0
}

// ReciprocalRank is 1/rank at which the question becomes answerable within
// the top k — the first expected document (any rule) or the last one needed
// (all rule) — or 0.
func ReciprocalRank(ranked, expected []string, k int, requireAll bool) float64 {
	want := set(expected)
	if len(want) == 0 {
		return 0
	}
	found := 0
	for i := 0; i < len(ranked) && i < k; i++ {
		if want[ranked[i]] {
			found++
			if !requireAll || found == len(want) {
				return 1 / float64(i+1)
			}
		}
	}
	return 0
}

var citation = regexp.MustCompile(`\[(\d{1,3})\]`)

// CitedDocuments resolves the answer's [n] markers (1-based, into the
// `sources` list the edge streamed) to unique documents. Out-of-range markers
// are ignored.
func CitedDocuments(answer string, sourceFilenames []string) []string {
	var cited []string
	for _, m := range citation.FindAllStringSubmatch(answer, -1) {
		n, err := strconv.Atoi(m[1])
		if err != nil || n < 1 || n > len(sourceFilenames) {
			continue
		}
		cited = append(cited, sourceFilenames[n-1])
	}
	return RankedDocuments(cited)
}

// QuestionResult is one evaluated question.
type QuestionResult struct {
	Answerable bool
	RequireAll bool // multi-hop: every expected document is needed
	Lang       string
	Ranked     []string // retrieved documents, best first
	Expected   []string // expected documents
	Cited      []string // documents the answer cites
	Answer     string   // the model's answer
	Answers    []string // accepted answers (answer + variants)
}

// Summary aggregates a question set. Retrieval, citation and answer-match
// rates are over the answerable questions; CorrectAbstention is over the
// unanswerable ones and FalseAbstention over the answerable ones.
type Summary struct {
	N, Answerable, Unanswerable int

	RecallAt    map[int]float64 // mean recall@k (any/all rule, see RecallAtK)
	HitAt       map[int]float64 // share answerable from the top k (any/all rule)
	MRR10       float64
	CitationHit float64 // share whose answer cites ≥1 expected document

	ExactMatch    float64 // normalized answer equals an accepted answer
	ContainsMatch float64 // an accepted answer occurs in the normalized answer

	CorrectAbstention float64 // unanswerable questions the model declined
	FalseAbstention   float64 // answerable questions the model declined
}

// Aggregate computes Summary for the given k cutoffs.
func Aggregate(results []QuestionResult, ks []int) Summary {
	s := Summary{N: len(results), RecallAt: map[int]float64{}, HitAt: map[int]float64{}}
	var mrr float64
	var cited, exact, contains, abstainedOK, abstainedWrong int
	for _, r := range results {
		if !r.Answerable {
			s.Unanswerable++
			if Abstained(r.Answer) {
				abstainedOK++
			}
			continue
		}
		s.Answerable++
		for _, k := range ks {
			s.RecallAt[k] += RecallAtK(r.Ranked, r.Expected, k, r.RequireAll)
			if HitAtK(r.Ranked, r.Expected, k, r.RequireAll) {
				s.HitAt[k]++
			}
		}
		mrr += ReciprocalRank(r.Ranked, r.Expected, 10, r.RequireAll)
		want := set(r.Expected)
		for _, c := range r.Cited {
			if want[c] {
				cited++
				break
			}
		}
		if ExactMatch(r.Answer, r.Answers, r.Lang) {
			exact++
		}
		if ContainsMatch(r.Answer, r.Answers, r.Lang) {
			contains++
		}
		if Abstained(r.Answer) {
			abstainedWrong++
		}
	}
	if s.Answerable > 0 {
		n := float64(s.Answerable)
		for _, k := range ks {
			s.RecallAt[k] /= n
			s.HitAt[k] /= n
		}
		s.MRR10 = mrr / n
		s.CitationHit = float64(cited) / n
		s.ExactMatch = float64(exact) / n
		s.ContainsMatch = float64(contains) / n
		s.FalseAbstention = float64(abstainedWrong) / n
	}
	if s.Unanswerable > 0 {
		s.CorrectAbstention = float64(abstainedOK) / float64(s.Unanswerable)
	}
	return s
}
