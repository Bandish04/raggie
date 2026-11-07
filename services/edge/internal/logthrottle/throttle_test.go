// SPDX-License-Identifier: Apache-2.0

package logthrottle

import (
	"testing"
	"time"
)

func TestAllowAtMostOncePerInterval(t *testing.T) {
	now := time.Unix(1000, 0)
	th := New(time.Minute)
	th.now = func() time.Time { return now }

	if ok, suppressed := th.Allow(); !ok || suppressed != 0 {
		t.Fatalf("first event: ok=%v suppressed=%d, want true/0", ok, suppressed)
	}
	for i := 0; i < 3; i++ {
		if ok, _ := th.Allow(); ok {
			t.Fatalf("event %d inside the interval must be suppressed", i)
		}
	}
	now = now.Add(time.Minute)
	ok, suppressed := th.Allow()
	if !ok || suppressed != 3 {
		t.Fatalf("after the interval: ok=%v suppressed=%d, want true/3", ok, suppressed)
	}
	if ok, _ := th.Allow(); ok {
		t.Fatal("the window restarts after an allowed event")
	}
}

func TestZeroIntervalAlwaysAllows(t *testing.T) {
	th := New(0)
	for i := 0; i < 3; i++ {
		if ok, suppressed := th.Allow(); !ok || suppressed != 0 {
			t.Fatalf("event %d: ok=%v suppressed=%d, want true/0", i, ok, suppressed)
		}
	}
}
