// SPDX-License-Identifier: Apache-2.0

//go:build !unix

package harness

// RaiseFileLimit is a no-op where RLIMIT_NOFILE does not exist.
func RaiseFileLimit() (uint64, error) { return 0, nil }
