// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"log/slog"
	"net"
	"net/http"
	"net/netip"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/ratelimit"
)

// rateLimitWindow is the window all per-minute limits are expressed in.
const rateLimitWindow = time.Minute

// rateLimitCheck is one bucket to charge: a namespaced key and its limit
// (requests per rateLimitWindow; <= 0 disables the check).
type rateLimitCheck struct {
	key   string
	limit int
}

// lastLimiterErrorLog throttles fail-open warnings during a Redis outage.
var lastLimiterErrorLog atomic.Int64

// checkRateLimits charges every bucket in order and returns the first denial.
// A limiter error fails OPEN (the request proceeds) and is logged at most once
// per 10s, so a Redis outage degrades protection instead of availability.
func checkRateLimits(ctx context.Context, limiter ratelimit.Limiter, logger *slog.Logger, checks ...rateLimitCheck) (ratelimit.Decision, bool) {
	if limiter == nil {
		return ratelimit.Decision{Allowed: true}, true
	}
	for _, c := range checks {
		if c.limit <= 0 || c.key == "" {
			continue
		}
		d, err := limiter.Allow(ctx, c.key, c.limit, rateLimitWindow)
		if err != nil {
			now := time.Now().Unix()
			if last := lastLimiterErrorLog.Load(); now-last >= 10 && lastLimiterErrorLog.CompareAndSwap(last, now) {
				logger.Warn("rate limiter unavailable; failing open", "err", err)
			}
			continue
		}
		if !d.Allowed {
			return d, false
		}
	}
	return ratelimit.Decision{Allowed: true}, true
}

// setRetryAfter writes a whole-second Retry-After header (at least 1).
func setRetryAfter(w http.ResponseWriter, d time.Duration) {
	secs := int((d + time.Second - 1) / time.Second)
	if secs < 1 {
		secs = 1
	}
	w.Header().Set("Retry-After", strconv.Itoa(secs))
}

// clientIP returns the caller's IP for per-IP limits. X-Forwarded-For is only
// honoured when the direct peer is a trusted proxy (TRUSTED_PROXY_CIDRS); then
// the rightmost hop that is NOT itself a trusted proxy is the client (entries
// to its left are client-controlled and spoofable).
func clientIP(r *http.Request, trusted []netip.Prefix) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		host = r.RemoteAddr
	}
	peer, err := netip.ParseAddr(host)
	if err != nil {
		return host
	}
	peer = peer.Unmap()
	if !isTrustedProxy(peer, trusted) {
		return peer.String()
	}
	hops := strings.Split(r.Header.Get("X-Forwarded-For"), ",")
	client := peer
	for i := len(hops) - 1; i >= 0; i-- {
		hop, err := netip.ParseAddr(strings.TrimSpace(hops[i]))
		if err != nil {
			break
		}
		client = hop.Unmap()
		if !isTrustedProxy(client, trusted) {
			break
		}
	}
	return client.String()
}

func isTrustedProxy(addr netip.Addr, trusted []netip.Prefix) bool {
	for _, p := range trusted {
		if p.Contains(addr) {
			return true
		}
	}
	return false
}
