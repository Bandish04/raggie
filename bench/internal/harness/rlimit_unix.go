// SPDX-License-Identifier: Apache-2.0

//go:build unix

package harness

import "syscall"

// RaiseFileLimit lifts the soft open-file limit to the hard limit so a load
// test can hold thousands of sockets (macOS defaults to 256). It returns the
// resulting soft limit.
func RaiseFileLimit() (uint64, error) {
	var lim syscall.Rlimit
	if err := syscall.Getrlimit(syscall.RLIMIT_NOFILE, &lim); err != nil {
		return 0, err
	}
	want := lim.Max
	// macOS rejects RLIM_INFINITY for NOFILE; OPEN_MAX-sized limits are enough.
	if want > 1<<20 {
		want = 1 << 20
	}
	for ; want > lim.Cur; want /= 2 {
		next := lim
		next.Cur = want
		if syscall.Setrlimit(syscall.RLIMIT_NOFILE, &next) == nil {
			return want, nil
		}
	}
	return lim.Cur, nil
}
