// SPDX-License-Identifier: Apache-2.0

package redisconn

import (
	"reflect"
	"strings"
	"testing"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
)

func TestFailoverOptionsFromSentinelConfig(t *testing.T) {
	cfg := config.Config{
		RedisURL:              "redis://ignored:6379/0",
		RedisSentinelAddrs:    []string{"sentinel-0:26379", "sentinel-1:26379"},
		RedisSentinelMaster:   "raggie",
		RedisPassword:         "redis-pass",
		RedisSentinelPassword: "sentinel-pass",
		RedisDB:               2,
	}
	opt := FailoverOptions(cfg)
	if opt == nil {
		t.Fatal("sentinel config must produce failover options")
	}
	if opt.MasterName != "raggie" || !reflect.DeepEqual(opt.SentinelAddrs, cfg.RedisSentinelAddrs) ||
		opt.Password != "redis-pass" || opt.SentinelPassword != "sentinel-pass" || opt.DB != 2 {
		t.Fatalf("unexpected failover options: %+v", opt)
	}
}

func TestFailoverOptionsNilWithoutSentinel(t *testing.T) {
	if FailoverOptions(config.Config{RedisURL: "redis://localhost:6379"}) != nil {
		t.Fatal("no sentinel config must mean no failover options")
	}
}

func TestNewSelectsMode(t *testing.T) {
	cases := []struct {
		name     string
		cfg      config.Config
		wantMode string
		wantNil  bool
	}{
		{"disabled", config.Config{}, ModeDisabled, true},
		{"url", config.Config{RedisURL: "redis://localhost:6379/1"}, ModeURL, false},
		{"sentinel wins over url", config.Config{
			RedisURL: "redis://localhost:6379", RedisSentinelAddrs: []string{"s:26379"}, RedisSentinelMaster: "m",
		}, ModeSentinel, false},
	}
	for _, tc := range cases {
		rdb, mode, err := New(tc.cfg)
		if err != nil {
			t.Fatalf("%s: %v", tc.name, err)
		}
		if mode != tc.wantMode || (rdb == nil) != tc.wantNil {
			t.Fatalf("%s: mode=%q nil=%v", tc.name, mode, rdb == nil)
		}
		if rdb != nil {
			_ = rdb.Close()
		}
	}
}

func TestURLModeAppliesPasswordWhenURLHasNone(t *testing.T) {
	opt, err := URLOptions(config.Config{RedisURL: "redis://redis:6379/3", RedisPassword: "p"})
	if err != nil || opt.Password != "p" || opt.DB != 3 || opt.Addr != "redis:6379" {
		t.Fatalf("opt=%+v err=%v", opt, err)
	}
	opt, err = URLOptions(config.Config{RedisURL: "redis://:fromurl@redis:6379", RedisPassword: "p"})
	if err != nil || opt.Password != "fromurl" {
		t.Fatalf("an explicit URL password must win: opt=%+v err=%v", opt, err)
	}
}

func TestNewRejectsInvalidURL(t *testing.T) {
	_, _, err := New(config.Config{RedisURL: "http://user:secret@not-redis"}) // #nosec G101 -- fake credential: asserts it is not echoed
	if err == nil {
		t.Fatal("expected an error for a non-redis URL")
	}
	if strings.Contains(err.Error(), "secret") {
		t.Fatalf("error must not echo URL credentials: %v", err)
	}
}
