// SPDX-License-Identifier: Apache-2.0

package report

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/alicangunduz/raggie/bench/internal/stackenv"
	"github.com/alicangunduz/raggie/bench/internal/sysinfo"
)

type demoBody struct {
	P95   time.Duration
	Ratio float64
	Cell  string
	Mem   uint64
}

func demoReport() Report {
	return Report{
		Name: "demo", Title: "Demo", DryRun: true,
		Started: time.Date(2026, 11, 4, 10, 0, 0, 0, time.UTC),
		System:  sysinfo.Info{CPUModel: "cpu", Cores: 2},
		Config:  []stackenv.KV{{Key: "k", Value: "v"}},
		Body:    demoBody{P95: 1500 * time.Microsecond, Ratio: 0.9876, Cell: "a|b", Mem: 1 << 20},
	}
}

func TestWriteRendersMarkdownJSONAndCSV(t *testing.T) {
	dir := t.TempDir()
	art, err := Write(dir, "testdata/templates", demoReport(), map[string]int{"x": 1}, [][]string{{"a", "b"}, {"1", "2"}})
	if err != nil {
		t.Fatal(err)
	}
	if filepath.Base(art.Markdown) != "demo-2026-11-04.md" || filepath.Base(art.JSON) != "demo-2026-11-04.json" ||
		filepath.Base(art.CSV) != "demo-2026-11-04.csv" {
		t.Fatalf("artifacts = %+v", art)
	}
	md, _ := os.ReadFile(art.Markdown)
	want := "# Demo (DRY RUN)\np95=1.500 ratio=98.8% cell=a\\|b mem=1.0 MiB\n"
	if string(md) != want {
		t.Fatalf("markdown = %q, want %q", md, want)
	}
	var j map[string]any
	b, _ := os.ReadFile(art.JSON)
	if err := json.Unmarshal(b, &j); err != nil {
		t.Fatal(err)
	}
	if j["raw"].(map[string]any)["x"].(float64) != 1 || j["report"].(map[string]any)["Name"] != "demo" {
		t.Fatalf("json = %s", b)
	}
	csv, _ := os.ReadFile(art.CSV)
	if string(csv) != "a,b\n1,2\n" {
		t.Fatalf("csv = %q", csv)
	}
}

func TestWriteNeverOverwrites(t *testing.T) {
	dir := t.TempDir()
	first, err := Write(dir, "testdata/templates", demoReport(), nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	second, err := Write(dir, "testdata/templates", demoReport(), nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	if first.Markdown == second.Markdown || !strings.HasSuffix(second.Markdown, "demo-2026-11-04-2.md") {
		t.Fatalf("second run = %s", second.Markdown)
	}
	if first.CSV != "" {
		t.Fatal("no CSV rows → no CSV file")
	}
}

func TestWriteFailsOnMissingTemplate(t *testing.T) {
	r := demoReport()
	r.Name = "nope"
	if _, err := Write(t.TempDir(), "testdata/templates", r, nil, nil); err == nil {
		t.Fatal("missing template must fail")
	}
}
