// SPDX-License-Identifier: Apache-2.0

// Package sysinfo records the machine and source revision a benchmark ran on,
// so every published number is reproducible. It never records the hostname,
// user name or any network identity.
package sysinfo

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"runtime"
	"strconv"
	"strings"
	"time"
)

// Info is the environment of one benchmark run.
type Info struct {
	CPUModel    string
	Cores       int
	MemoryBytes uint64
	OS          string // e.g. "darwin 24.4.0" / "linux 6.8.0-45-generic"
	Arch        string
	GoVersion   string
	GitSHA      string
	GitDirty    bool
	Docker      *DockerInfo // nil when docker is unavailable
}

// DockerInfo describes the docker engine the stack runs in. On macOS/Windows
// this is the Linux VM, whose CPU/RAM bound the stack, not the host's.
type DockerInfo struct {
	ServerVersion string
	NCPU          int
	MemBytes      uint64
}

// Hardware is a one-line summary for report headers.
func (i Info) Hardware() string {
	return fmt.Sprintf("%s, %d cores, %s RAM", i.CPUModel, i.Cores, HumanBytes(i.MemoryBytes))
}

// Collect gathers Info; every probe is best-effort and bounded. probeDocker
// runs `docker info` (the engine the stack runs in); dry runs and tests skip
// it so they never touch Docker.
func Collect(ctx context.Context, repoRoot string, probeDocker bool) Info {
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	info := Info{
		Cores:     runtime.NumCPU(),
		Arch:      runtime.GOARCH,
		GoVersion: runtime.Version(),
		OS:        runtime.GOOS,
		CPUModel:  "unknown",
		GitSHA:    "unknown",
	}
	if rel := run(ctx, "uname", "-r"); rel != "" {
		info.OS += " " + rel
	}
	switch runtime.GOOS {
	case "darwin":
		if m := run(ctx, "sysctl", "-n", "machdep.cpu.brand_string"); m != "" {
			info.CPUModel = m
		}
		if b, err := strconv.ParseUint(run(ctx, "sysctl", "-n", "hw.memsize"), 10, 64); err == nil {
			info.MemoryBytes = b
		}
	case "linux":
		if f, err := os.Open("/proc/cpuinfo"); err == nil {
			if m := parseCPUInfo(f); m != "" {
				info.CPUModel = m
			}
			_ = f.Close()
		}
		if f, err := os.Open("/proc/meminfo"); err == nil {
			info.MemoryBytes = parseMemInfo(f)
			_ = f.Close()
		}
	}
	if sha := run(ctx, "git", "-C", repoRoot, "rev-parse", "HEAD"); sha != "" {
		info.GitSHA = sha
		info.GitDirty = run(ctx, "git", "-C", repoRoot, "status", "--porcelain", "--untracked-files=no") != ""
	}
	if !probeDocker {
		return info
	}
	if d, ok := parseDockerInfo(run(ctx, "docker", "info", "--format", "{{.ServerVersion}}|{{.NCPU}}|{{.MemTotal}}")); ok {
		info.Docker = &d
	}
	return info
}

func run(ctx context.Context, name string, args ...string) string {
	out, err := exec.CommandContext(ctx, name, args...).Output() // #nosec G204 -- fixed probe commands
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

func parseCPUInfo(r io.Reader) string {
	var implementer, part string
	sc := bufio.NewScanner(r)
	for sc.Scan() {
		key, value, ok := strings.Cut(sc.Text(), ":")
		if !ok {
			continue
		}
		key, value = strings.TrimSpace(key), strings.TrimSpace(value)
		switch key {
		case "model name", "Model", "cpu model":
			if value != "" {
				return value
			}
		case "CPU implementer":
			implementer = value
		case "CPU part":
			part = value
		}
	}
	if implementer != "" {
		return fmt.Sprintf("ARM implementer %s part %s", implementer, part)
	}
	return ""
}

func parseMemInfo(r io.Reader) uint64 {
	sc := bufio.NewScanner(r)
	for sc.Scan() {
		fields := strings.Fields(sc.Text())
		if len(fields) >= 2 && fields[0] == "MemTotal:" {
			kb, err := strconv.ParseUint(fields[1], 10, 64)
			if err == nil {
				return kb * 1024
			}
		}
	}
	return 0
}

func parseDockerInfo(s string) (DockerInfo, bool) {
	parts := strings.Split(strings.TrimSpace(s), "|")
	if len(parts) != 3 || parts[0] == "" {
		return DockerInfo{}, false
	}
	ncpu, err1 := strconv.Atoi(parts[1])
	mem, err2 := strconv.ParseUint(parts[2], 10, 64)
	if err1 != nil || err2 != nil {
		return DockerInfo{}, false
	}
	return DockerInfo{ServerVersion: parts[0], NCPU: ncpu, MemBytes: mem}, true
}

// HumanBytes renders a byte count with binary units.
func HumanBytes(b uint64) string {
	const unit = 1024
	if b < unit {
		return fmt.Sprintf("%d B", b)
	}
	div, exp := uint64(unit), 0
	for n := b / unit; n >= unit; n /= unit {
		div *= unit
		exp++
	}
	return fmt.Sprintf("%.1f %ciB", float64(b)/float64(div), "KMGTPE"[exp])
}
