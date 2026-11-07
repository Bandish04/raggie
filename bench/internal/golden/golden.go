// SPDX-License-Identifier: Apache-2.0

// Package golden loads the exact-answer golden set (examples/golden/golden.yaml):
// questions with their answer (null = unanswerable from the corpus), accepted
// answer variants, the documents that hold the answer and verbatim evidence.
//
// Schema and scoring rules: examples/golden/README.md. The file is a mapping
// with `version: 1`, the items under `questions` (or `items`), an optional
// `corpus` — the corpus directory, relative to the golden file — and an
// optional `exclude` (basenames never uploaded); a bare list of items is also
// accepted. A corpus README.md describes the corpus and is never a document.
package golden

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"
)

// Question types.
const (
	TypeSingleFact   = "single-fact"
	TypeTableLookup  = "table-lookup"
	TypeMultiHop     = "multi-hop"
	TypeTemporal     = "temporal/version"
	TypeUnanswerable = "negative/unanswerable"
	TypeOCR          = "ocr"
)

// Types lists every known type in report order.
var Types = []string{TypeSingleFact, TypeTableLookup, TypeMultiHop, TypeTemporal, TypeUnanswerable, TypeOCR}

// Item is one golden question.
type Item struct {
	ID                string     `yaml:"id"`
	Question          string     `yaml:"question"`
	Language          string     `yaml:"language"`
	Answer            *string    `yaml:"answer"` // nil = not answerable from the corpus
	AnswerVariants    []string   `yaml:"answer_variants"`
	ExpectedDocuments []string   `yaml:"expected_documents"`
	Evidence          []Evidence `yaml:"evidence"`
	Type              string     `yaml:"type"`
	Difficulty        Scalar     `yaml:"difficulty"`
	Department        string     `yaml:"department"`
	AbsentTerms       []string   `yaml:"absent_terms"` // negative questions: strings found nowhere in the corpus
	Notes             string     `yaml:"notes"`
}

// RequiresAllDocuments reports the spec's retrieval rule: a multi-hop
// question needs every expected document; any other type is answered by any
// one of them.
func (i Item) RequiresAllDocuments() bool { return i.Type == TypeMultiHop }

// Evidence is one verbatim supporting quote. The file gives it as
// {document, quote}; a plain string is accepted as a quote without document.
type Evidence struct {
	Document string `yaml:"document"`
	Quote    string `yaml:"quote"`
}

func (e *Evidence) UnmarshalYAML(n *yaml.Node) error {
	switch n.Kind {
	case yaml.ScalarNode:
		*e = Evidence{Quote: n.Value}
		return nil
	case yaml.MappingNode:
		type plain Evidence
		return n.Decode((*plain)(e))
	default:
		return fmt.Errorf("line %d: evidence must be a quote or {document, quote}", n.Line)
	}
}

// Answerable reports whether the corpus answers the question.
func (i Item) Answerable() bool { return i.Answer != nil }

// Answers is the answer plus its accepted variants (empty when unanswerable).
func (i Item) Answers() []string {
	if i.Answer == nil {
		return nil
	}
	return append([]string{*i.Answer}, i.AnswerVariants...)
}

// Scalar decodes any YAML scalar (e.g. a difficulty given as "hard" or 3) as
// its string form.
type Scalar string

func (s *Scalar) UnmarshalYAML(n *yaml.Node) error {
	if n.Kind != yaml.ScalarNode {
		return fmt.Errorf("line %d: expected a scalar", n.Line)
	}
	*s = Scalar(n.Value)
	return nil
}

// Set is a loaded golden file.
type Set struct {
	Path    string // the file it was loaded from
	Corpus  string // corpus dir as written in the file (relative to it), may be empty
	Exclude []string
	Items   []Item
}

type document struct {
	Version   int      `yaml:"version"`
	Corpus    string   `yaml:"corpus"`
	Exclude   []string `yaml:"exclude"`
	Items     []Item   `yaml:"items"`
	Questions []Item   `yaml:"questions"`
}

// Load parses a golden file.
func Load(path string) (*Set, error) {
	b, err := os.ReadFile(path) // #nosec G304 -- operator-chosen golden file
	if err != nil {
		return nil, err
	}
	var root yaml.Node
	if err := yaml.Unmarshal(b, &root); err != nil {
		return nil, fmt.Errorf("parse %s: %w", path, err)
	}
	s := &Set{Path: path}
	if len(root.Content) == 0 {
		return s, nil
	}
	switch top := root.Content[0]; top.Kind {
	case yaml.SequenceNode:
		err = top.Decode(&s.Items)
	case yaml.MappingNode:
		var d document
		if err = top.Decode(&d); err == nil && d.Version != 0 && d.Version != 1 {
			err = fmt.Errorf("unsupported golden version %d", d.Version)
		}
		if err == nil {
			s.Corpus, s.Exclude, s.Items = d.Corpus, d.Exclude, d.Items
			if len(s.Items) == 0 {
				s.Items = d.Questions
			}
		}
	default:
		err = errors.New("expected a list of items or a mapping with `items`")
	}
	if err != nil {
		return nil, fmt.Errorf("parse %s: %w", path, err)
	}
	return s, nil
}

// CorpusDir resolves the corpus directory: override when set, else the file's
// `corpus` relative to the golden file, else "".
func (s *Set) CorpusDir(override string) string {
	switch {
	case override != "":
		return override
	case s.Corpus == "":
		return ""
	case filepath.IsAbs(s.Corpus):
		return s.Corpus
	default:
		return filepath.Join(filepath.Dir(s.Path), s.Corpus)
	}
}

// CorpusFiles lists the corpus documents (sorted by basename), minus
// exclusions, README.md files and dotfiles.
func (s *Set) CorpusFiles(corpusDir string) ([]string, error) {
	if corpusDir == "" {
		return nil, errors.New("the golden set names no corpus directory (pass -corpus)")
	}
	excluded := map[string]bool{"README.md": true}
	for _, e := range s.Exclude {
		excluded[e] = true
	}
	var files []string
	err := filepath.WalkDir(corpusDir, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() || excluded[d.Name()] || strings.HasPrefix(d.Name(), ".") {
			return nil
		}
		files = append(files, path)
		return nil
	})
	sort.Slice(files, func(i, j int) bool { return filepath.Base(files[i]) < filepath.Base(files[j]) })
	return files, err
}

var knownType = func() map[string]bool {
	m := map[string]bool{}
	for _, t := range Types {
		m[t] = true
	}
	return m
}()

// Validate checks every item against the schema and the corpus: unique ids,
// a question, language tr|en, a known type, at least one expected document for
// answerable items, and every expected document present under a unique
// basename.
func (s *Set) Validate(corpusDir string) error {
	files, err := s.CorpusFiles(corpusDir)
	if err != nil {
		return err
	}
	names := map[string]int{}
	for _, f := range files {
		names[filepath.Base(f)]++
	}
	var problems []error
	ids := map[string]bool{}
	for _, it := range s.Items {
		if ids[it.ID] || it.ID == "" {
			problems = append(problems, fmt.Errorf("duplicate or empty id %q", it.ID))
		}
		ids[it.ID] = true
		if strings.TrimSpace(it.Question) == "" {
			problems = append(problems, fmt.Errorf("%s: empty question", it.ID))
		}
		if it.Language != "tr" && it.Language != "en" {
			problems = append(problems, fmt.Errorf("%s: language %q is not tr|en", it.ID, it.Language))
		}
		if !knownType[it.Type] {
			problems = append(problems, fmt.Errorf("%s: unknown type %q", it.ID, it.Type))
		}
		if it.Answerable() && len(it.ExpectedDocuments) == 0 {
			problems = append(problems, fmt.Errorf("%s: answerable but no expected_documents", it.ID))
		}
		for _, d := range it.ExpectedDocuments {
			switch names[d] {
			case 0:
				problems = append(problems, fmt.Errorf("%s: expected document %s is not in the corpus", it.ID, d))
			case 1:
			default:
				problems = append(problems, fmt.Errorf("%s: expected document %s is ambiguous (%d files)", it.ID, d, names[d]))
			}
		}
	}
	return errors.Join(problems...)
}

// Filter selects items.
type Filter struct {
	Language       string // "" = all
	Type           string // "" = all
	AnswerableOnly bool
	Limit          int // 0 = all
}

// Filter returns the matching items in file order.
func (s *Set) Filter(f Filter) []Item {
	var out []Item
	for _, it := range s.Items {
		if (f.Language != "" && it.Language != f.Language) ||
			(f.Type != "" && it.Type != f.Type) ||
			(f.AnswerableOnly && !it.Answerable()) {
			continue
		}
		out = append(out, it)
		if f.Limit > 0 && len(out) == f.Limit {
			break
		}
	}
	return out
}
