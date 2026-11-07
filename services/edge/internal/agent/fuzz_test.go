// SPDX-License-Identifier: Apache-2.0

package agent

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"testing"
)

// Model-produced tool arguments: accepted only as one JSON object, re-encoded
// compactly, and hashed over exactly the bytes that are forwarded.
func FuzzNormalizeArgs(f *testing.F) {
	for _, s := range []string{`{"jql":"a"}`, ``, `  `, `null`, `[1]`, `{"a":1} {"b":2}`, `{"a":`, `{"n":12345678901234567890}`} {
		f.Add(s)
	}
	f.Fuzz(func(t *testing.T, raw string) {
		out, hash, err := normalizeArgs(raw)
		if err != nil {
			return
		}
		if !json.Valid(out) || len(out) == 0 || out[0] != '{' {
			t.Fatalf("normalized args are not a JSON object: %s", out)
		}
		sum := sha256.Sum256(out)
		if hash != hex.EncodeToString(sum[:]) {
			t.Fatal("audit hash does not cover the forwarded arguments")
		}
	})
}
