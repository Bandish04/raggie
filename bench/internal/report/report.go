// SPDX-License-Identifier: Apache-2.0

// Package report writes a benchmark result as a dated markdown file (rendered
// from docs/benchmarks/templates) plus the raw numbers as JSON and CSV next to
// it. An existing result is never overwritten.
package report

import (
	"encoding/csv"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"text/template"
	"time"

	"github.com/alicangunduz/raggie/bench/internal/stackenv"
	"github.com/alicangunduz/raggie/bench/internal/stats"
	"github.com/alicangunduz/raggie/bench/internal/sysinfo"
)

// Report is everything a result file shows. Body is harness-specific and is
// what the harness's template renders.
type Report struct {
	Name         string // file slug and template name, e.g. "a2-retrieval"
	Title        string
	DryRun       bool
	Started      time.Time
	Duration     time.Duration
	Command      string
	System       sysinfo.Info
	StackEnvPath string
	StackEnv     []stackenv.KV
	Config       []stackenv.KV // harness parameters
	Notes        []string      // caveats that must travel with the numbers
	Body         any
}

// Artifacts are the files one Write produced.
type Artifacts struct {
	Markdown, JSON, CSV string
}

var funcs = template.FuncMap{
	"ms":    stats.Millis,
	"pct":   func(f float64) string { return fmt.Sprintf("%.1f%%", f*100) },
	"f3":    func(f float64) string { return fmt.Sprintf("%.3f", f) },
	"bytes": sysinfo.HumanBytes,
	"cell":  func(s string) string { return strings.ReplaceAll(strings.ReplaceAll(s, "|", `\|`), "\n", " ") },
	"date":  func(t time.Time) string { return t.UTC().Format("2006-01-02 15:04:05 UTC") },
	"short": func(s string) string {
		if len(s) > 12 {
			return s[:12]
		}
		return s
	},
}

// Write renders r with templatesDir/<r.Name>.md.tmpl (plus every _*.md.tmpl
// partial) into dir as <name>-<date>.md, and writes raw as .json and csvRows
// (when non-empty) as .csv alongside.
func Write(dir, templatesDir string, r Report, raw any, csvRows [][]string) (Artifacts, error) {
	partials, err := filepath.Glob(filepath.Join(templatesDir, "_*.md.tmpl"))
	if err != nil {
		return Artifacts{}, err
	}
	main := filepath.Join(templatesDir, r.Name+".md.tmpl")
	if _, err := os.Stat(main); err != nil {
		return Artifacts{}, fmt.Errorf("template for %q: %w", r.Name, err)
	}
	tmpl, err := template.New(filepath.Base(main)).Funcs(funcs).ParseFiles(append([]string{main}, partials...)...)
	if err != nil {
		return Artifacts{}, err
	}
	var md strings.Builder
	if err := tmpl.ExecuteTemplate(&md, filepath.Base(main), r); err != nil {
		return Artifacts{}, fmt.Errorf("render %s: %w", main, err)
	}

	if err := os.MkdirAll(dir, 0o750); err != nil {
		return Artifacts{}, err
	}
	base, err := freeBase(dir, r.Name+"-"+r.Started.Format("2006-01-02"))
	if err != nil {
		return Artifacts{}, err
	}
	art := Artifacts{Markdown: base + ".md", JSON: base + ".json"}
	if err := os.WriteFile(art.Markdown, []byte(md.String()), 0o600); err != nil {
		return Artifacts{}, err
	}
	meta := r
	meta.Body = nil
	j, err := json.MarshalIndent(map[string]any{"report": meta, "body": r.Body, "raw": raw}, "", "  ")
	if err != nil {
		return Artifacts{}, err
	}
	if err := os.WriteFile(art.JSON, append(j, '\n'), 0o600); err != nil {
		return Artifacts{}, err
	}
	if len(csvRows) > 0 {
		art.CSV = base + ".csv"
		f, err := os.OpenFile(art.CSV, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600) // #nosec G304 -- path built from the output dir
		if err != nil {
			return Artifacts{}, err
		}
		w := csv.NewWriter(f)
		_ = w.WriteAll(csvRows)
		if err := errors.Join(w.Error(), f.Close()); err != nil {
			return Artifacts{}, err
		}
	}
	return art, nil
}

// freeBase returns dir/name, or dir/name-N for the first N whose .md is free.
func freeBase(dir, name string) (string, error) {
	for n := 1; n < 1000; n++ {
		base := filepath.Join(dir, name)
		if n > 1 {
			base = fmt.Sprintf("%s-%d", base, n)
		}
		if _, err := os.Stat(base + ".md"); errors.Is(err, fs.ErrNotExist) {
			return base, nil
		}
	}
	return "", fmt.Errorf("no free result name for %s in %s", name, dir)
}
