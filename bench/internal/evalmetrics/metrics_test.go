// SPDX-License-Identifier: Apache-2.0

package evalmetrics

import (
	"math"
	"testing"
)

func near(a, b float64) bool { return math.Abs(a-b) < 1e-9 }

func TestRankedDocumentsDedupesChunksInOrder(t *testing.T) {
	got := RankedDocuments([]string{"a.pdf", "b.md", "a.pdf", "", "c.txt", "b.md"})
	want := []string{"a.pdf", "b.md", "c.txt"}
	if len(got) != len(want) {
		t.Fatalf("got %v", got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("got %v, want %v", got, want)
		}
	}
}

// Spec (examples/golden/README.md): a multi-hop question needs ALL expected
// documents; any other type is answered by ANY one of them.
func TestRetrievalAnyRule(t *testing.T) {
	ranked := []string{"x", "a", "y", "b"}
	exp := []string{"a", "b"} // equivalent sources
	for k, want := range map[int]float64{1: 0, 2: 1, 10: 1} {
		if r := RecallAtK(ranked, exp, k, false); r != want {
			t.Errorf("any recall@%d = %v, want %v", k, r, want)
		}
		if h := HitAtK(ranked, exp, k, false); h != (want == 1) {
			t.Errorf("any hit@%d = %v", k, h)
		}
	}
	if rr := ReciprocalRank(ranked, exp, 10, false); !near(rr, 0.5) {
		t.Fatalf("any rr = %v, want 1/2 (first expected at rank 2)", rr)
	}
	if RecallAtK(ranked, nil, 5, false) != 0 || HitAtK(ranked, nil, 5, false) {
		t.Fatal("no expected docs")
	}
}

func TestRetrievalAllRule(t *testing.T) {
	ranked := []string{"x", "a", "y", "b"}
	exp := []string{"a", "b"} // both needed
	if r := RecallAtK(ranked, exp, 2, true); !near(r, 0.5) {
		t.Fatalf("all recall@2 = %v, want 0.5 (partial credit)", r)
	}
	if HitAtK(ranked, exp, 3, true) || !HitAtK(ranked, exp, 4, true) {
		t.Fatal("all hit needs every expected document within k")
	}
	if rr := ReciprocalRank(ranked, exp, 10, true); !near(rr, 0.25) {
		t.Fatalf("all rr = %v, want 1/4 (the set is complete at rank 4)", rr)
	}
	if rr := ReciprocalRank(ranked, exp, 3, true); rr != 0 {
		t.Fatalf("all rr beyond the cutoff = %v", rr)
	}
}

func TestCitedDocuments(t *testing.T) {
	sources := []string{"a.pdf", "a.pdf", "b.md", "c.txt"}
	answer := "Yanıt a.pdf kaynağında [1], ayrıca [3][4] ve [9] ile [0]."
	got := CitedDocuments(answer, sources)
	want := map[string]bool{"a.pdf": true, "b.md": true, "c.txt": true}
	if len(got) != len(want) {
		t.Fatalf("got %v", got)
	}
	for _, d := range got {
		if !want[d] {
			t.Fatalf("unexpected %q in %v", d, got)
		}
	}
	if len(CitedDocuments("no markers", sources)) != 0 {
		t.Fatal("no markers → no citations")
	}
}

func TestAggregate(t *testing.T) {
	results := []QuestionResult{
		{Answerable: true, Lang: "tr", Ranked: []string{"a", "x"}, Expected: []string{"a", "z"}, Cited: []string{"a"},
			Answer: "Yanıt 18 gün [1].", Answers: []string{"18 gün"}},
		{Answerable: true, Lang: "en", Ranked: []string{"x", "b"}, Expected: []string{"b"}, Cited: []string{"x"},
			Answer: "I could not find this.", Answers: []string{"85 EUR"}},
		{Answerable: true, Lang: "en", Ranked: []string{"x"}, Expected: []string{"c"}, Answer: "85 EUR", Answers: []string{"85 EUR"}},
		{Answerable: false, Lang: "en", Ranked: []string{"x"}, Answer: "The documents contain no information on this."},
		{Answerable: false, Lang: "tr", Ranked: []string{"x"}, Answer: "Cevap 42."},
	}
	agg := Aggregate(results, []int{1, 2})
	if agg.N != 5 || agg.Answerable != 3 || agg.Unanswerable != 2 {
		t.Fatalf("counts = %+v", agg)
	}
	// Retrieval and citation metrics only cover answerable items.
	if !near(agg.RecallAt[1], 1.0/3) || !near(agg.RecallAt[2], 2.0/3) || !near(agg.HitAt[2], 2.0/3) {
		t.Fatalf("recall/hit = %+v %+v", agg.RecallAt, agg.HitAt)
	}
	if !near(agg.MRR10, (1+0.5+0)/3) || !near(agg.CitationHit, 1.0/3) {
		t.Fatalf("mrr = %v citation = %v", agg.MRR10, agg.CitationHit)
	}
	if !near(agg.ExactMatch, 1.0/3) || !near(agg.ContainsMatch, 2.0/3) {
		t.Fatalf("exact = %v contains = %v", agg.ExactMatch, agg.ContainsMatch)
	}
	if !near(agg.CorrectAbstention, 0.5) || !near(agg.FalseAbstention, 1.0/3) {
		t.Fatalf("abstention correct = %v false = %v", agg.CorrectAbstention, agg.FalseAbstention)
	}
}

func TestAggregateMultiHopNeedsEveryDocument(t *testing.T) {
	results := []QuestionResult{
		{Answerable: true, RequireAll: true, Ranked: []string{"a", "x", "b"}, Expected: []string{"a", "b"}},
		{Answerable: true, RequireAll: true, Ranked: []string{"a", "x"}, Expected: []string{"a", "b"}},
	}
	agg := Aggregate(results, []int{3})
	if !near(agg.HitAt[3], 0.5) || !near(agg.RecallAt[3], 0.75) || !near(agg.MRR10, (1.0/3)/2) {
		t.Fatalf("hit %v recall %v mrr %v", agg.HitAt[3], agg.RecallAt[3], agg.MRR10)
	}
}
