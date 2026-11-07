// SPDX-License-Identifier: Apache-2.0

package bus

import (
	"context"
	"fmt"
	"os"
	"testing"
	"time"
)

// Live Redis test; skipped unless REDIS_URL is set.
func TestPublishAndAcquireOnce(t *testing.T) {
	url := os.Getenv("REDIS_URL")
	if url == "" {
		t.Skip("REDIS_URL not set")
	}
	b, err := New(url)
	if err != nil {
		t.Fatal(err)
	}
	defer b.Close()
	ctx := context.Background()

	key := fmt.Sprintf("idem-test-%d", time.Now().UnixNano())
	first, err := b.AcquireOnce(ctx, key, time.Minute)
	if err != nil || !first {
		t.Fatalf("first AcquireOnce should be true: %v %v", first, err)
	}
	dup, err := b.AcquireOnce(ctx, key, time.Minute)
	if err != nil || dup {
		t.Fatalf("duplicate AcquireOnce should be false: %v %v", dup, err)
	}

	stream := fmt.Sprintf("test.chat.completed.%d", time.Now().UnixNano())
	if err := b.Publish(ctx, stream, map[string]any{"message_id": "m1", "workspace_id": "ws1"}); err != nil {
		t.Fatal(err)
	}
	n, err := b.rdb.XLen(ctx, stream).Result()
	if err != nil || n != 1 {
		t.Fatalf("expected 1 stream entry, got %d (err %v)", n, err)
	}
	b.rdb.Del(ctx, stream)
}
