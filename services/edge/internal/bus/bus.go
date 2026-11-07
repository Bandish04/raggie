// SPDX-License-Identifier: Apache-2.0

// Package bus is the edge's Redis-Streams producer + idempotency helper.
package bus

import (
	"context"
	"encoding/json"
	"time"

	"github.com/redis/go-redis/v9"
)

// ChatCompleted is the topic the auto-evaluator (eval worker) consumes. Must match the
// workers' topics.py and contracts/events.md.
const ChatCompleted = "raggie.chat.completed"

type Bus struct {
	rdb *redis.Client
}

func New(redisURL string) (*Bus, error) {
	opt, err := redis.ParseURL(redisURL)
	if err != nil {
		return nil, err
	}
	return &Bus{rdb: redis.NewClient(opt)}, nil
}

// NewFromClient wraps an existing client (e.g. a Sentinel failover client from
// redisconn) so the bus and every other Redis user share one pool.
func NewFromClient(rdb *redis.Client) *Bus {
	return &Bus{rdb: rdb}
}

func (b *Bus) Close() error { return b.rdb.Close() }

// Redis exposes the shared client so other Redis-backed features (the rate
// limiter) reuse one connection pool.
func (b *Bus) Redis() *redis.Client { return b.rdb }

func (b *Bus) Ready(ctx context.Context) error { return b.rdb.Ping(ctx).Err() }

// Publish appends an event to a stream (XADD) with the shared {data: json} envelope.
func (b *Bus) Publish(ctx context.Context, topic string, payload map[string]any) error {
	data, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	return b.rdb.XAdd(ctx, &redis.XAddArgs{
		Stream: topic,
		Values: map[string]any{"data": string(data)},
	}).Err()
}

// AcquireOnce returns true the first time a key is seen within ttl (SETNX), false
// for duplicates — used to dedup retried chat requests by Idempotency-Key.
func (b *Bus) AcquireOnce(ctx context.Context, key string, ttl time.Duration) (bool, error) {
	return b.rdb.SetNX(ctx, "idem:"+key, "1", ttl).Result()
}
