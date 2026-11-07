// SPDX-License-Identifier: Apache-2.0

package golden

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const fixture = "../../eval/testdata/golden.yaml"

func TestLoadFixture(t *testing.T) {
	set, err := Load(fixture)
	if err != nil {
		t.Fatal(err)
	}
	if len(set.Items) != 5 {
		t.Fatalf("items = %d", len(set.Items))
	}
	first := set.Items[0]
	if first.ID != "f-001" || first.Language != "tr" || first.Answer == nil || *first.Answer != "18 iş günü" ||
		len(first.AnswerVariants) != 2 || first.Type != TypeSingleFact || first.Difficulty != "easy" {
		t.Fatalf("first = %+v", first)
	}
	if set.Items[1].Difficulty != "2" {
		t.Fatalf("numeric difficulty = %q, want \"2\"", set.Items[1].Difficulty)
	}
	last := set.Items[4]
	if last.Answerable() || last.Type != TypeUnanswerable || len(last.AbsentTerms) != 1 || last.Notes == "" {
		t.Fatalf("unanswerable item = %+v", last)
	}
	if first.Department != "insan-kaynaklari" {
		t.Fatalf("department = %q", first.Department)
	}
	// Evidence accepts {document, quote} maps and plain quote strings.
	ev := set.Items[3].Evidence
	if len(ev) != 3 || ev[0] != (Evidence{Document: "org_chart.md", Quote: "Finans direktörü Elif Kaya'dır"}) ||
		ev[1] != (Evidence{Quote: "Satın alma birimi finans direktörüne bağlıdır"}) || ev[2].Document != "fiyat_listesi_2026.txt" {
		t.Fatalf("evidence = %+v", ev)
	}
	if got := set.CorpusDir(""); got != filepath.Join(filepath.Dir(fixture), "corpus") {
		t.Fatalf("corpus dir = %q", got)
	}
	if got := set.CorpusDir("/override"); got != "/override" {
		t.Fatalf("override = %q", got)
	}
	if err := set.Validate(set.CorpusDir("")); err != nil {
		t.Fatal(err)
	}
}

func TestLoadAcceptsBareListAndQuestionsKey(t *testing.T) {
	item := `- id: "x1"
  question: "q?"
  language: "en"
  answer: "a"
  expected_documents: ["a.md"]
  evidence: ["a"]
  type: "single-fact"
  difficulty: "easy"
`
	dir := t.TempDir()
	bare := filepath.Join(dir, "bare.yaml")
	keyed := filepath.Join(dir, "keyed.yaml")
	_ = os.WriteFile(bare, []byte(item), 0o600)
	_ = os.WriteFile(keyed, []byte("questions:\n"+indent(item)), 0o600)
	for _, p := range []string{bare, keyed} {
		set, err := Load(p)
		if err != nil || len(set.Items) != 1 || set.Items[0].ID != "x1" {
			t.Fatalf("%s: %+v, %v", p, set, err)
		}
		if set.CorpusDir("") != "" {
			t.Fatal("no corpus field and no override → empty")
		}
	}
}

func indent(s string) string {
	lines := strings.Split(strings.TrimRight(s, "\n"), "\n")
	for i := range lines {
		lines[i] = "  " + lines[i]
	}
	return strings.Join(lines, "\n") + "\n"
}

func TestLoadRejectsUnknownVersionAndBadEvidence(t *testing.T) {
	dir := t.TempDir()
	for name, body := range map[string]string{
		"version":  "version: 2\nquestions: []\n",
		"evidence": "questions:\n  - id: x\n    evidence:\n      - [nested, list]\n",
	} {
		p := filepath.Join(dir, name+".yaml")
		_ = os.WriteFile(p, []byte(body), 0o600)
		if _, err := Load(p); err == nil {
			t.Errorf("%s: accepted", name)
		}
	}
}

func TestValidateCatchesBadItems(t *testing.T) {
	set, err := Load(fixture)
	if err != nil {
		t.Fatal(err)
	}
	corpus := set.CorpusDir("")
	cases := map[string]func(*Item){
		"unknown type":            func(i *Item) { i.Type = "trivia" },
		"bad language":            func(i *Item) { i.Language = "de" },
		"missing document":        func(i *Item) { i.ExpectedDocuments = []string{"nope.md"} },
		"answerable without docs": func(i *Item) { i.ExpectedDocuments = nil },
		"empty question":          func(i *Item) { i.Question = " " },
	}
	for name, mutate := range cases {
		s, _ := Load(fixture)
		mutate(&s.Items[0])
		if err := s.Validate(corpus); err == nil {
			t.Errorf("%s: accepted", name)
		}
	}
	dup, _ := Load(fixture)
	dup.Items[1].ID = dup.Items[0].ID
	if err := dup.Validate(corpus); err == nil || !strings.Contains(err.Error(), "duplicate") {
		t.Fatalf("duplicate id: %v", err)
	}
}

func TestCorpusFilesAndFilter(t *testing.T) {
	set, _ := Load(fixture)
	files, err := set.CorpusFiles(set.CorpusDir(""))
	if err != nil || len(files) != 4 { // the corpus README.md is never a document
		t.Fatalf("files = %v, %v", files, err)
	}
	if got := set.Filter(Filter{Language: "en"}); len(got) != 2 {
		t.Fatalf("en = %d", len(got))
	}
	if got := set.Filter(Filter{AnswerableOnly: true}); len(got) != 4 {
		t.Fatalf("answerable = %d", len(got))
	}
	if got := set.Filter(Filter{Type: TypeMultiHop}); len(got) != 1 || got[0].ID != "f-004" {
		t.Fatalf("multi-hop = %+v", got)
	}
	if got := set.Filter(Filter{Limit: 2}); len(got) != 2 {
		t.Fatalf("limit = %d", len(got))
	}
}

// The real golden set must stay consistent with its corpus.
func TestRepositoryGoldenSetIsValid(t *testing.T) {
	path := "../../../examples/golden/golden.yaml"
	if _, err := os.Stat(path); err != nil {
		t.Skip("examples/golden/golden.yaml not present")
	}
	set, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	corpus := set.CorpusDir("")
	if corpus == "" {
		t.Fatal("the repository golden set must name its corpus (top-level `corpus:`, relative to the file)")
	}
	if err := set.Validate(corpus); err != nil {
		t.Fatal(err)
	}
	files, err := set.CorpusFiles(corpus)
	if err != nil {
		t.Fatal(err)
	}
	for _, f := range files {
		if filepath.Base(f) == "README.md" {
			t.Fatal("the corpus README must not be uploaded as a document")
		}
	}
	unanswerable, perType := 0, map[string]int{}
	for _, it := range set.Items {
		perType[it.Type]++
		if !it.Answerable() {
			unanswerable++
			if len(it.ExpectedDocuments) != 0 {
				t.Errorf("%s: unanswerable but lists expected documents", it.ID)
			}
		}
		for _, e := range it.Evidence {
			if e.Quote == "" {
				t.Errorf("%s: empty evidence quote", it.ID)
			}
		}
	}
	t.Logf("%d questions, %d corpus documents, %d unanswerable, per type %v", len(set.Items), len(files), unanswerable, perType)
	if len(set.Items) == 0 || len(files) == 0 || unanswerable != perType[TypeUnanswerable] {
		t.Fatalf("questions=%d files=%d unanswerable=%d negatives=%d", len(set.Items), len(files), unanswerable, perType[TypeUnanswerable])
	}
}
