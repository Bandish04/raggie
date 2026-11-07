// SPDX-License-Identifier: Apache-2.0

package harness

import (
	"flag"
	"fmt"
	"path/filepath"

	"github.com/alicangunduz/raggie/bench/internal/golden"
)

// GoldenFlags locate the golden set and its corpus.
type GoldenFlags struct {
	Path   string
	Corpus string
}

// Bind registers -golden and -corpus.
func (g *GoldenFlags) Bind(fs *flag.FlagSet) {
	fs.StringVar(&g.Path, "golden", "", "golden set (default: examples/golden/golden.yaml; the bench/eval/testdata fixture for -dry-run)")
	fs.StringVar(&g.Corpus, "corpus", "", "corpus directory (default: the golden file's `corpus`, relative to it)")
}

// LoadGolden loads and validates the golden set and resolves its corpus.
func (r *Run) LoadGolden(g GoldenFlags) (*golden.Set, string, error) {
	path := g.Path
	if path == "" {
		path = filepath.Join(r.Repo, "examples", "golden", "golden.yaml")
		if r.Common.DryRun {
			path = filepath.Join(r.Repo, "bench", "eval", "testdata", "golden.yaml")
		}
	}
	set, err := golden.Load(path)
	if err != nil {
		return nil, "", fmt.Errorf("golden set: %w", err)
	}
	corpus := set.CorpusDir(g.Corpus)
	if err := set.Validate(corpus); err != nil {
		return nil, "", fmt.Errorf("golden set %s is inconsistent with corpus %q: %w", path, corpus, err)
	}
	return set, corpus, nil
}

// Questions returns every question text of the set (for latency/load
// harnesses, which only need realistic queries).
func Questions(set *golden.Set) []string {
	out := make([]string, 0, len(set.Items))
	for _, it := range set.Items {
		out = append(out, it.Question)
	}
	return out
}
