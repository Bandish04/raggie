// SPDX-License-Identifier: Apache-2.0

package widgetauth

import (
	"strings"
	"testing"
	"time"
)

// Untrusted bearer tokens: no panics, and acceptance implies a valid HMAC over
// the exact header.payload that was presented.
func FuzzParseAndVerify(f *testing.F) {
	tok, _ := Mint("secret", "ws", time.Hour, time.Unix(1_700_000_000, 0))
	f.Add(tok)
	f.Add("a.b.c")
	f.Add("..")
	f.Add("eyJhbGciOiJub25lIn0.eyJhdWQiOiJ3aWRnZXQifQ.")
	f.Fuzz(func(t *testing.T, token string) {
		now := time.Unix(1_700_000_000, 0)
		claims, err := ParseHS256("secret", token, now)
		if err != nil {
			if c, verr := Verify("secret", token, now, time.Hour); verr == nil || c != nil {
				t.Fatal("Verify accepted a token ParseHS256 rejected")
			}
			return
		}
		parts := strings.Split(token, ".")
		if len(parts) != 3 || sign("secret", parts[0]+"."+parts[1]) != parts[2] {
			t.Fatalf("accepted token without a valid signature: %q (%v)", token, claims)
		}
	})
}
