// SPDX-License-Identifier: Apache-2.0

// Package stackenv reads the benchmark-relevant, non-secret settings of the
// stack under test from its env file (scripts/e2e-stack.sh writes one), so a
// report records e.g. whether the reranker was on or which embedding provider
// ran. Only whitelisted keys are ever read into a report: secrets, URLs and
// hosts never leave the env file.
package stackenv

import (
	"bufio"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// KV is one setting.
type KV struct {
	Key, Value string
}

// allowed are the keys a report may show. Nothing here may hold a secret, a
// URL or a hostname.
var allowed = map[string]bool{
	"RAGGIE_ENV":                       true,
	"EMBEDDINGS_PROVIDER":              true,
	"EMBEDDINGS_MODEL":                 true,
	"EMBEDDING_DIM":                    true,
	"EMBEDDINGS_CACHE_ENABLED":         true,
	"EMBEDDINGS_BAKE":                  true,
	"RERANKER_ENABLED":                 true,
	"RERANKER_PROVIDER":                true,
	"RERANKER_MODEL":                   true,
	"RERANK_ENABLED":                   true,
	"RERANK_CANDIDATE_K":               true,
	"RETRIEVE_CANDIDATE_K":             true,
	"RETRIEVE_CONTEXT_K":               true,
	"RETRIEVE_MAX_CHUNKS_PER_DOCUMENT": true,
	"EMBED_QUERY_TIMEOUT_MS":           true,
	"RERANK_TIMEOUT_MS":                true,
	"LLMAAS_CHAT_MODEL":                true,
	"LLMAAS_CHAT_MAX_CONCURRENCY":      true,
	"LLMAAS_EMBED_MAX_CONCURRENCY":     true,
	"MOCKLLM_TOKEN_DELAY_MS":           true,
	"RATE_LIMIT_ENABLED":               true,
	"RATE_LIMIT_CHAT_USER_PER_MINUTE":  true,
	"AGENT_UNIFIED_LOOP":               true,
	"EVAL_SAMPLE_RATE":                 true,
}

// DefaultPath mirrors scripts/e2e-stack.sh: $RAGGIE_E2E_DIR/app.env, else
// ${XDG_CACHE_HOME:-$HOME/.cache}/raggie-e2e/app.env.
func DefaultPath() string {
	if dir := os.Getenv("RAGGIE_E2E_DIR"); dir != "" {
		return filepath.Join(dir, "app.env")
	}
	cache := os.Getenv("XDG_CACHE_HOME")
	if cache == "" {
		home, _ := os.UserHomeDir()
		cache = filepath.Join(home, ".cache")
	}
	return filepath.Join(cache, "raggie-e2e", "app.env")
}

// Read returns the whitelisted settings in path, sorted by key. The last
// assignment of a key wins; inline " # comments" and surrounding quotes are
// stripped.
func Read(path string) ([]KV, error) {
	f, err := os.Open(path) // #nosec G304 -- operator-chosen env file
	if err != nil {
		return nil, err
	}
	defer f.Close()
	values := map[string]string{}
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		key, value, ok := strings.Cut(line, "=")
		key = strings.TrimSpace(strings.TrimPrefix(key, "export "))
		if !ok || !allowed[key] {
			continue
		}
		if i := strings.Index(value, " #"); i >= 0 {
			value = value[:i]
		}
		values[key] = strings.Trim(strings.TrimSpace(value), `"'`)
	}
	if err := sc.Err(); err != nil {
		return nil, err
	}
	out := make([]KV, 0, len(values))
	for k, v := range values {
		out = append(out, KV{k, v})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Key < out[j].Key })
	return out, nil
}

// Lookup returns key's value, or def.
func Lookup(kvs []KV, key, def string) string {
	for _, kv := range kvs {
		if kv.Key == key {
			return kv.Value
		}
	}
	return def
}
