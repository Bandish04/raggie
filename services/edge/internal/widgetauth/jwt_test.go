// SPDX-License-Identifier: Apache-2.0

package widgetauth

import (
	"errors"
	"testing"
	"time"
)

func TestMintVerifyRoundTrip(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	tok, err := Mint("secret", "ws-123", 30*time.Minute, now)
	if err != nil {
		t.Fatalf("mint: %v", err)
	}
	claims, err := Verify("secret", tok, now.Add(time.Minute), time.Hour)
	if err != nil {
		t.Fatalf("verify: %v", err)
	}
	if claims.WorkspaceID != "ws-123" || claims.Aud != "widget" {
		t.Fatalf("unexpected claims: %+v", claims)
	}
}

func TestVerifyRejectsWrongSecret(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	tok, _ := Mint("secret", "ws-123", time.Hour, now)
	if _, err := Verify("other-secret", tok, now, time.Hour); !errors.Is(err, ErrBadSignature) {
		t.Fatalf("expected ErrBadSignature, got %v", err)
	}
}

func TestVerifyRejectsExpired(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	tok, _ := Mint("secret", "ws-123", time.Minute, now)
	if _, err := Verify("secret", tok, now.Add(2*time.Minute), time.Hour); !errors.Is(err, ErrExpired) {
		t.Fatalf("expected ErrExpired, got %v", err)
	}
}

func TestVerifyRejectsTamper(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	tok, _ := Mint("secret", "ws-123", time.Hour, now)
	// Flip the last character of the signature.
	bad := tok[:len(tok)-1]
	if tok[len(tok)-1] == 'A' {
		bad += "B"
	} else {
		bad += "A"
	}
	if _, err := Verify("secret", bad, now, time.Hour); err == nil {
		t.Fatal("expected verification to fail on a tampered token")
	}
}

func TestVerifyRejectsMalformed(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	if _, err := Verify("secret", "not-a-jwt", now, time.Hour); !errors.Is(err, ErrMalformed) {
		t.Fatalf("expected ErrMalformed, got %v", err)
	}
}

// Each minted widget token carries a fresh, unguessable session id (sid) that
// the edge binds widget conversations to.
func TestMintIssuesUniqueSessionID(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	seen := map[string]bool{}
	for i := 0; i < 50; i++ {
		tok, err := Mint("secret", "ws-123", time.Hour, now)
		if err != nil {
			t.Fatal(err)
		}
		claims, err := Verify("secret", tok, now, time.Hour)
		if err != nil {
			t.Fatal(err)
		}
		if len(claims.SessionID) < 32 {
			t.Fatalf("session id too short: %q", claims.SessionID)
		}
		if seen[claims.SessionID] {
			t.Fatalf("duplicate session id %q", claims.SessionID)
		}
		seen[claims.SessionID] = true
	}
}
