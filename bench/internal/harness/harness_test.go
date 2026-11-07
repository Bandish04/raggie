// SPDX-License-Identifier: Apache-2.0

package harness

import (
	"context"
	"os"
	"testing"

	"github.com/alicangunduz/raggie/bench/internal/fakestack"
)

func TestDryRunStartAndCloseCleanUp(t *testing.T) {
	c := &Common{DryRun: true, OutDir: t.TempDir()}
	r, err := Start(context.Background(), "a2-retrieval", "t", c, fakestack.Options{}, 4)
	if err != nil {
		t.Fatal(err)
	}
	if !r.Session.Bootstrapped || r.Report.Name != "a2-retrieval" || !r.Report.DryRun {
		t.Fatalf("run = %+v", r.Report)
	}
	state := r.tempState
	if _, err := os.Stat(state); err != nil {
		t.Fatalf("state dir: %v", err)
	}
	r.Close()
	if _, err := os.Stat(state); !os.IsNotExist(err) {
		t.Fatalf("dry-run credential dir left behind: %v", err)
	}
}

func TestRepoRootFindsBench(t *testing.T) {
	root, err := RepoRoot()
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(root + "/bench/go.mod"); err != nil {
		t.Fatal(err)
	}
	t.Setenv("RAGGIE_REPO_ROOT", t.TempDir())
	if _, err := RepoRoot(); err == nil {
		t.Fatal("a directory outside the repo must not resolve")
	}
}
