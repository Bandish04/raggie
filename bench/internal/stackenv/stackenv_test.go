// SPDX-License-Identifier: Apache-2.0

package stackenv

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestReadKeepsOnlyWhitelistedKeys(t *testing.T) {
	path := filepath.Join(t.TempDir(), "app.env")
	content := strings.Join([]string{
		"# comment",
		"RERANK_ENABLED=true",
		"EMBEDDINGS_PROVIDER=local               # local | openai_compatible",
		"JWT_SECRET=0123456789abcdef0123456789abcdef",
		"LLMAAS_API_KEY=sk-should-never-leak",
		"DATABASE_URL=postgresql://raggie:pw@postgres:5432/raggie",
		"EMBEDDINGS_UPSTREAM_BASE_URL=https://api.example.com/v1",
		"MOCKLLM_TOKEN_DELAY_MS=15",
		"RATE_LIMIT_ENABLED=false",
		"RATE_LIMIT_ENABLED=true", // last assignment wins, like the shell
		"EMBEDDINGS_MODEL=\"intfloat/multilingual-e5-large\"",
		"",
	}, "\n")
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	kvs, err := Read(path)
	if err != nil {
		t.Fatal(err)
	}
	got := map[string]string{}
	for _, kv := range kvs {
		got[kv.Key] = kv.Value
	}
	want := map[string]string{
		"RERANK_ENABLED":         "true",
		"EMBEDDINGS_PROVIDER":    "local",
		"MOCKLLM_TOKEN_DELAY_MS": "15",
		"RATE_LIMIT_ENABLED":     "true",
		"EMBEDDINGS_MODEL":       "intfloat/multilingual-e5-large",
	}
	if len(got) != len(want) {
		t.Fatalf("got %v", got)
	}
	for k, v := range want {
		if got[k] != v {
			t.Errorf("%s = %q, want %q", k, got[k], v)
		}
	}
	for i := 1; i < len(kvs); i++ {
		if kvs[i-1].Key > kvs[i].Key {
			t.Fatal("keys must be sorted for stable reports")
		}
	}
}

func TestNoSecretLikeKeyIsWhitelisted(t *testing.T) {
	for k := range allowed {
		for _, bad := range []string{"SECRET", "PASSWORD", "TOKEN", "API_KEY", "_URL", "KEY"} {
			if strings.Contains(k, bad) && k != "MOCKLLM_TOKEN_DELAY_MS" {
				t.Errorf("whitelisted key %s looks like it could carry a secret or a host", k)
			}
		}
	}
}

func TestDefaultPathFollowsE2EScript(t *testing.T) {
	t.Setenv("RAGGIE_E2E_DIR", "/x/e2e")
	if got := DefaultPath(); got != "/x/e2e/app.env" {
		t.Fatalf("got %q", got)
	}
	t.Setenv("RAGGIE_E2E_DIR", "")
	t.Setenv("XDG_CACHE_HOME", "/cache")
	if got := DefaultPath(); got != "/cache/raggie-e2e/app.env" {
		t.Fatalf("got %q", got)
	}
}

func TestLookup(t *testing.T) {
	kvs := []KV{{"A", "1"}}
	if Lookup(kvs, "A", "x") != "1" || Lookup(kvs, "B", "x") != "x" {
		t.Fatal("Lookup")
	}
}
