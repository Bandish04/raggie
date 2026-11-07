// SPDX-License-Identifier: Apache-2.0

// Package harness is the scaffolding every benchmark command shares: common
// flags, connecting to the stack (or to an in-process fake for -dry-run),
// seeding a workspace with the golden corpus, and writing the dated report.
package harness

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/alicangunduz/raggie/bench/internal/fakestack"
	"github.com/alicangunduz/raggie/bench/internal/report"
	"github.com/alicangunduz/raggie/bench/internal/stack"
	"github.com/alicangunduz/raggie/bench/internal/stackenv"
	"github.com/alicangunduz/raggie/bench/internal/sysinfo"
)

// Common holds the flags every harness accepts.
type Common struct {
	OutDir    string
	DryRun    bool
	StackEnv  string
	Timeout   time.Duration
	Workspace string
}

// Bind registers the common flags.
func (c *Common) Bind(fs *flag.FlagSet, defaultTimeout time.Duration) {
	fs.StringVar(&c.OutDir, "out", "", "result directory (default: docs/benchmarks; a temp dir for -dry-run)")
	fs.BoolVar(&c.DryRun, "dry-run", false, "run against an in-process fake stack (validates the harness; numbers are meaningless)")
	fs.StringVar(&c.StackEnv, "stack-env", stackenv.DefaultPath(), "env file of the stack under test; only whitelisted non-secret keys are reported")
	fs.DurationVar(&c.Timeout, "timeout", defaultTimeout, "overall deadline")
	fs.StringVar(&c.Workspace, "workspace", "", "reuse this already-indexed workspace id instead of creating and seeding one")
}

// Run is one harness execution.
type Run struct {
	Common  *Common
	Repo    string
	Session *stack.Session
	Fake    *fakestack.Stack // set in -dry-run
	Report  report.Report

	tempState string // dry-run credential dir, removed on Close
}

// RepoRoot finds the repository root (the directory holding bench/go.mod),
// starting from RAGGIE_REPO_ROOT or the working directory.
func RepoRoot() (string, error) {
	start := os.Getenv("RAGGIE_REPO_ROOT")
	if start == "" {
		var err error
		if start, err = os.Getwd(); err != nil {
			return "", err
		}
	}
	for dir := start; ; dir = filepath.Dir(dir) {
		// #nosec G703 -- walks up from the operator's cwd / RAGGIE_REPO_ROOT; only stats a fixed file name
		if _, err := os.Stat(filepath.Join(dir, "bench", "go.mod")); err == nil {
			return dir, nil
		}
		if filepath.Dir(dir) == dir {
			return "", errors.New("repository root not found (run from inside the repo or set RAGGIE_REPO_ROOT)")
		}
	}
}

// Start connects to the stack (or starts the fake) and pre-fills the report.
func Start(ctx context.Context, name, title string, c *Common, fake fakestack.Options, maxConns int) (*Run, error) {
	repo, err := RepoRoot()
	if err != nil {
		return nil, err
	}
	r := &Run{Common: c, Repo: repo}
	var cfg stack.Config
	if c.DryRun {
		r.Fake = fakestack.New(fake)
		if r.tempState, err = os.MkdirTemp("", "raggie-bench-state-"); err != nil {
			r.Close()
			return nil, err
		}
		cfg = stack.Config{CPURL: r.Fake.CPURL(), EdgeURL: r.Fake.EdgeURL(), StateDir: r.tempState}
		if c.OutDir == "" {
			if c.OutDir, err = os.MkdirTemp("", "raggie-bench-dryrun-"); err != nil {
				r.Close()
				return nil, err
			}
		}
	} else {
		cfg = stack.ConfigFromEnv(repo)
		if c.OutDir == "" {
			c.OutDir = filepath.Join(repo, "docs", "benchmarks")
		}
	}
	cfg.MaxConns = maxConns
	if r.Session, err = stack.Connect(ctx, cfg); err != nil {
		r.Close()
		return nil, err
	}
	r.Report = report.Report{
		Name:    name,
		Title:   title,
		DryRun:  c.DryRun,
		Started: time.Now().UTC(),
		Command: commandLine(name),
		System:  sysinfo.Collect(ctx, repo, !c.DryRun),
	}
	if !c.DryRun && c.StackEnv != "" {
		if kvs, err := stackenv.Read(c.StackEnv); err == nil {
			r.Report.StackEnvPath, r.Report.StackEnv = c.StackEnv, kvs
		}
	}
	return r, nil
}

func commandLine(name string) string {
	return strings.TrimSpace("cd bench && go run ./" + name + " " + strings.Join(os.Args[1:], " "))
}

// StackSetting returns a whitelisted stack setting, or def.
func (r *Run) StackSetting(key, def string) string {
	return stackenv.Lookup(r.Report.StackEnv, key, def)
}

// Close releases the fake stack and its temporary credentials, if any.
func (r *Run) Close() {
	if r.Fake != nil {
		r.Fake.Close()
	}
	if r.tempState != "" {
		_ = os.RemoveAll(r.tempState)
	}
}

// Finish writes the report.
func (r *Run) Finish(body any, config []stackenv.KV, notes []string, raw any, csvRows [][]string) (report.Artifacts, error) {
	r.Report.Duration = time.Since(r.Report.Started).Round(time.Second)
	r.Report.Body, r.Report.Config = body, config
	if r.Common.DryRun {
		notes = append([]string{"DRY RUN against the in-process fake stack: these numbers validate the harness only and describe no real system."}, notes...)
	}
	r.Report.Notes = notes
	return report.Write(r.Common.OutDir, filepath.Join(r.Repo, "docs", "benchmarks", "templates"), r.Report, raw, csvRows)
}

// Workspace returns the -workspace id, or creates a fresh INTERNAL workspace.
func (r *Run) Workspace(ctx context.Context, prefix string) (stack.Workspace, bool, error) {
	if r.Common.Workspace != "" {
		return stack.Workspace{ID: r.Common.Workspace}, false, nil
	}
	ws, err := r.Session.CreateWorkspace(ctx, r.Session.Me.OrgID, fmt.Sprintf("%s %s", prefix, time.Now().UTC().Format("2006-01-02 15:04:05")))
	return ws, true, err
}

// IngestSummary describes a corpus upload.
type IngestSummary struct {
	Files     int
	Succeeded int
	Failed    []string // filenames
	Wall      time.Duration
}

// UploadAndWait uploads files (bounded concurrency) and waits until every
// document is ingested or failed.
func (r *Run) UploadAndWait(ctx context.Context, workspaceID string, files []string, concurrency int, poll time.Duration) (IngestSummary, error) {
	start := time.Now()
	sum := IngestSummary{Files: len(files)}
	ids := make([]string, len(files))
	errs := make([]error, len(files))
	sem := make(chan struct{}, max(1, concurrency))
	var wg sync.WaitGroup
	for i, f := range files {
		wg.Add(1)
		sem <- struct{}{}
		go func(i int, f string) {
			defer func() { <-sem; wg.Done() }()
			data, err := os.ReadFile(f) // #nosec G304 -- corpus files listed by the harness
			if err != nil {
				errs[i] = err
				return
			}
			doc, err := r.Session.Upload(ctx, workspaceID, filepath.Base(f), data)
			ids[i], errs[i] = doc.ID, err
		}(i, f)
	}
	wg.Wait()
	if err := errors.Join(errs...); err != nil {
		return sum, fmt.Errorf("upload corpus: %w", err)
	}
	final, err := r.Session.WaitDocuments(ctx, workspaceID, ids, poll, nil)
	sum.Wall = time.Since(start).Round(time.Millisecond)
	for _, d := range final {
		if d.Status == stack.StatusSuccess {
			sum.Succeeded++
		} else if d.Status == stack.StatusFailed {
			sum.Failed = append(sum.Failed, d.Filename)
		}
	}
	return sum, err
}

// KV builds a config entry.
func KV(key string, value any) stackenv.KV { return stackenv.KV{Key: key, Value: fmt.Sprint(value)} }
