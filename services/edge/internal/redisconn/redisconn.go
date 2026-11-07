// SPDX-License-Identifier: Apache-2.0

// Package redisconn builds the edge's single Redis client from configuration:
// a Sentinel-aware failover client when REDIS_SENTINEL_ADDRS/MASTER are set
// (HA: follows master promotion transparently), otherwise a plain client from
// REDIS_URL. Every Redis user in the edge (event bus, idempotency, rate
// limiter) shares the client built here.
package redisconn

import (
	"errors"
	"strings"

	"github.com/redis/go-redis/v9"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
)

const (
	ModeDisabled = ""         // no Redis configured
	ModeURL      = "url"      // single node / proxy via REDIS_URL
	ModeSentinel = "sentinel" // Sentinel-managed master
)

// FailoverOptions maps the Sentinel settings onto go-redis options, or returns
// nil when Sentinel is not configured.
func FailoverOptions(cfg config.Config) *redis.FailoverOptions {
	if len(cfg.RedisSentinelAddrs) == 0 || cfg.RedisSentinelMaster == "" {
		return nil
	}
	return &redis.FailoverOptions{
		MasterName:       cfg.RedisSentinelMaster,
		SentinelAddrs:    append([]string(nil), cfg.RedisSentinelAddrs...),
		SentinelPassword: cfg.RedisSentinelPassword,
		Password:         cfg.RedisPassword,
		DB:               cfg.RedisDB,
	}
}

// URLOptions parses REDIS_URL; REDIS_PASSWORD fills in when the URL has none.
func URLOptions(cfg config.Config) (*redis.Options, error) {
	opt, err := redis.ParseURL(cfg.RedisURL)
	if err != nil {
		// go-redis errors can quote the URL (credentials included); keep only
		// a generic, actionable message.
		return nil, errors.New("invalid REDIS_URL (expected redis:// or rediss://)")
	}
	if opt.Password == "" && cfg.RedisPassword != "" {
		opt.Password = cfg.RedisPassword
	}
	return opt, nil
}

// New returns the configured client and its mode. With neither Sentinel nor
// REDIS_URL configured it returns (nil, ModeDisabled, nil).
func New(cfg config.Config) (*redis.Client, string, error) {
	if opt := FailoverOptions(cfg); opt != nil {
		return redis.NewFailoverClient(opt), ModeSentinel, nil
	}
	if strings.TrimSpace(cfg.RedisURL) == "" {
		return nil, ModeDisabled, nil
	}
	opt, err := URLOptions(cfg)
	if err != nil {
		return nil, ModeDisabled, err
	}
	return redis.NewClient(opt), ModeURL, nil
}
