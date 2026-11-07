// SPDX-License-Identifier: Apache-2.0

// Package promscrape reads single values from a Prometheus text exposition
// (the edge's internal /metrics listener), without a client dependency.
package promscrape

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
)

// Scrape fetches a metrics page, presenting token as a bearer when set.
func Scrape(ctx context.Context, c *http.Client, url, token string) (string, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return "", err
	}
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	resp, err := c.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("scrape %s: HTTP %d", url, resp.StatusCode)
	}
	b, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	return string(b), err
}

// Value returns the first sample of metric name (any labels).
func Value(body, name string) (float64, bool) {
	sc := bufio.NewScanner(strings.NewReader(body))
	for sc.Scan() {
		line := sc.Text()
		if strings.HasPrefix(line, "#") || !strings.HasPrefix(line, name) {
			continue
		}
		rest := line[len(name):]
		if rest == "" || (rest[0] != ' ' && rest[0] != '{') {
			continue // a longer metric sharing the prefix
		}
		if rest[0] == '{' {
			end := strings.IndexByte(rest, '}')
			if end < 0 {
				continue
			}
			rest = rest[end+1:]
		}
		fields := strings.Fields(rest)
		if len(fields) == 0 {
			continue
		}
		if v, err := strconv.ParseFloat(fields[0], 64); err == nil {
			return v, true
		}
	}
	return 0, false
}
