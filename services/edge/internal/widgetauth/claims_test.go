// SPDX-License-Identifier: Apache-2.0

package widgetauth

import (
	"errors"
	"testing"
	"time"
)

const ttl = 30 * time.Minute

func signed(t *testing.T, claims map[string]any) string {
	t.Helper()
	tok, err := SignHS256("secret", claims)
	if err != nil {
		t.Fatal(err)
	}
	return tok
}

func TestParseRequiresExp(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	tok := signed(t, map[string]any{"aud": "admin", "sub": "u1"})
	if _, err := ParseHS256("secret", tok, now); !errors.Is(err, ErrInvalidClaims) {
		t.Fatalf("token without exp: err = %v, want ErrInvalidClaims", err)
	}
	for _, exp := range []any{"9999999999", true, nil} {
		tok := signed(t, map[string]any{"aud": "admin", "exp": exp})
		if _, err := ParseHS256("secret", tok, now); !errors.Is(err, ErrInvalidClaims) {
			t.Fatalf("exp=%#v: err = %v, want ErrInvalidClaims", exp, err)
		}
	}
}

func TestParseRejectsFutureIat(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	tok := signed(t, map[string]any{"exp": now.Add(time.Hour).Unix(), "iat": now.Add(10 * time.Minute).Unix()})
	if _, err := ParseHS256("secret", tok, now); !errors.Is(err, ErrInvalidClaims) {
		t.Fatalf("future iat: err = %v", err)
	}
	// Within the clock-skew allowance is fine.
	tok = signed(t, map[string]any{"exp": now.Add(time.Hour).Unix(), "iat": now.Add(30 * time.Second).Unix()})
	if _, err := ParseHS256("secret", tok, now); err != nil {
		t.Fatalf("iat within skew: %v", err)
	}
}

func TestVerifyEnforcesWidgetClaims(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	base := func() map[string]any {
		return map[string]any{"aud": "widget", "wid": "ws", "sid": "s", "iat": now.Unix(), "exp": now.Add(ttl).Unix()}
	}
	if _, err := Verify("secret", signed(t, base()), now, ttl); err != nil {
		t.Fatalf("valid widget token rejected: %v", err)
	}
	for name, mutate := range map[string]func(map[string]any){
		"no exp":            func(c map[string]any) { delete(c, "exp") },
		"no iat":            func(c map[string]any) { delete(c, "iat") },
		"iat in the future": func(c map[string]any) { c["iat"] = now.Add(5 * time.Minute).Unix() },
		"lifetime too long": func(c map[string]any) { c["exp"] = now.Add(ttl + 5*time.Minute).Unix() },
		"exp before iat":    func(c map[string]any) { c["exp"] = now.Add(-time.Second).Unix(); c["iat"] = now.Unix() },
		"wrong audience":    func(c map[string]any) { c["aud"] = "admin" },
		"missing workspace": func(c map[string]any) { delete(c, "wid") },
	} {
		c := base()
		mutate(c)
		if _, err := Verify("secret", signed(t, c), now, ttl); err == nil {
			t.Errorf("%s: accepted", name)
		}
	}
	// A lifetime within TTL + skew passes (minting clock jitter).
	c := base()
	c["exp"] = now.Add(ttl + 30*time.Second).Unix()
	if _, err := Verify("secret", signed(t, c), now, ttl); err != nil {
		t.Fatalf("lifetime within skew rejected: %v", err)
	}
}

func TestVerifyRequiresPositiveMaxLifetime(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	tok, _ := Mint("secret", "ws", ttl, now)
	if _, err := Verify("secret", tok, now, 0); err == nil {
		t.Fatal("a zero max lifetime must reject every token (fail closed)")
	}
}
