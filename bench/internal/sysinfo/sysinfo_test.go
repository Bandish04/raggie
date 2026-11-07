// SPDX-License-Identifier: Apache-2.0

package sysinfo

import (
	"context"
	"os"
	"runtime"
	"strings"
	"testing"
)

func open(t *testing.T, name string) *os.File {
	t.Helper()
	f, err := os.Open("testdata/" + name) // #nosec G304 -- fixed test fixtures
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = f.Close() })
	return f
}

func TestParseCPUInfo(t *testing.T) {
	if got := parseCPUInfo(open(t, "cpuinfo")); got != "AMD EPYC 7B13 64-Core Processor" {
		t.Fatalf("model = %q", got)
	}
	// ARM /proc/cpuinfo has no model name: fall back to the implementer/part ids.
	if got := parseCPUInfo(open(t, "cpuinfo-arm")); got != "ARM implementer 0x41 part 0xd0c" {
		t.Fatalf("arm model = %q", got)
	}
}

func TestParseMemInfo(t *testing.T) {
	if got := parseMemInfo(open(t, "meminfo")); got != 16303428*1024 {
		t.Fatalf("mem = %d", got)
	}
}

func TestParseDockerInfo(t *testing.T) {
	d, ok := parseDockerInfo("29.4.0|8|6283878400\n")
	if !ok || d.ServerVersion != "29.4.0" || d.NCPU != 8 || d.MemBytes != 6283878400 {
		t.Fatalf("docker = %+v ok=%v", d, ok)
	}
	if _, ok := parseDockerInfo("garbage"); ok {
		t.Fatal("garbage must not parse")
	}
}

func TestCollectFillsTheBasics(t *testing.T) {
	info := Collect(context.Background(), "../../..", false) // never touch Docker in tests
	if info.Cores != runtime.NumCPU() || info.Arch != runtime.GOARCH || info.OS == "" || info.GoVersion == "" {
		t.Fatalf("info = %+v", info)
	}
	if info.Docker != nil {
		t.Fatal("docker must not be probed when probeDocker is false")
	}
	if len(info.GitSHA) != 40 && info.GitSHA != "unknown" {
		t.Fatalf("git sha = %q", info.GitSHA)
	}
}

func TestHumanBytes(t *testing.T) {
	for in, want := range map[uint64]string{0: "0 B", 1023: "1023 B", 1536: "1.5 KiB", 17179869184: "16.0 GiB"} {
		if got := HumanBytes(in); got != want {
			t.Errorf("HumanBytes(%d) = %q, want %q", in, got, want)
		}
	}
	if !strings.Contains(Info{CPUModel: "X", Cores: 2, MemoryBytes: 1 << 30}.Hardware(), "X, 2 cores, 1.0 GiB RAM") {
		t.Fatal("Hardware summary")
	}
}
