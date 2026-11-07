// SPDX-License-Identifier: Apache-2.0

//go:build !linux

package httpserver

// Current RSS and open fds need /proc; like the Prometheus process collector,
// they are omitted elsewhere (the edge ships as a Linux image).
func processResidentMemoryBytes() (uint64, bool) { return 0, false }

func processOpenFDs() (int, bool) { return 0, false }
