// SPDX-License-Identifier: Apache-2.0

//go:build linux

package httpserver

import "os"

func processResidentMemoryBytes() (uint64, bool) {
	raw, err := os.ReadFile("/proc/self/statm")
	if err != nil {
		return 0, false
	}
	return parseStatmRSS(raw, os.Getpagesize())
}

func processOpenFDs() (int, bool) {
	entries, err := os.ReadDir("/proc/self/fd")
	if err != nil {
		return 0, false
	}
	return len(entries), true
}
