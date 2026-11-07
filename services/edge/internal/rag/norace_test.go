// SPDX-License-Identifier: Apache-2.0

//go:build !race

package rag

// raceEnabled reports whether the test binary runs under the race detector,
// whose 5-10x slowdown makes wall-clock latency assertions meaningless.
const raceEnabled = false
