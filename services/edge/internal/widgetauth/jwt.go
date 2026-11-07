// SPDX-License-Identifier: Apache-2.0

// Package widgetauth mints and verifies the HS256 JWTs the edge handles: the
// short-lived audience-scoped widget tokens (aud=widget) it issues itself, and
// the admin/user access tokens (aud=admin) minted by the control-plane that
// gate the internal chat path. It is a minimal, dependency-free HS256
// implementation — the edge only ever needs HS256, so the full JWT surface is
// unnecessary and a hand-rolled HMAC keeps the build lean.
//
// A4 (ARCHITECTURE §9): widget tokens carry aud=widget + a wid (workspace) claim
// and are honoured ONLY on the public chat surface; the admin surface honours
// aud=admin. The internal chat path verifies aud=admin and then checks the
// caller's workspace access.
package widgetauth

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"strings"
	"time"
)

// Errors returned by the verifiers. Callers map these to 401.
var (
	ErrMalformed     = errors.New("widgetauth: malformed token")
	ErrBadSignature  = errors.New("widgetauth: bad signature")
	ErrExpired       = errors.New("widgetauth: token expired")
	ErrWrongAudience = errors.New("widgetauth: wrong audience")
	ErrInvalidClaims = errors.New("widgetauth: missing or invalid time claims")
)

// ClockSkew is the tolerance for clocks that disagree between the issuer and
// the edge (iat slightly in the future, lifetime slightly over the TTL).
const ClockSkew = time.Minute

// Claims is the verified payload of a widget token.
type Claims struct {
	Aud         string `json:"aud"`
	WorkspaceID string `json:"wid"`
	// SessionID (sid) is a random per-token id. Widget conversations are bound
	// to it server-side, so a leaked conversation id alone cannot be resumed.
	// Empty for tokens minted before sid existed.
	SessionID string `json:"sid"`
	Iat       int64  `json:"iat"`
	Exp       int64  `json:"exp"`
}

const audWidget = "widget"

var b64 = base64.RawURLEncoding

// SignHS256 signs an arbitrary claim set (compact JWS, HS256).
func SignHS256(secret string, claims map[string]any) (string, error) {
	header := `{"alg":"HS256","typ":"JWT"}`
	payload, err := json.Marshal(claims)
	if err != nil {
		return "", err
	}
	signing := b64.EncodeToString([]byte(header)) + "." + b64.EncodeToString(payload)
	return signing + "." + sign(secret, signing), nil
}

// ParseHS256 verifies the signature, requires a numeric exp in the future and,
// when present, an iat no later than now + ClockSkew, then returns the decoded
// claims. A token without exp never verifies: it would be valid forever. It
// does not check audience — callers assert the audience/role they require.
func ParseHS256(secret, token string, now time.Time) (map[string]any, error) {
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		return nil, ErrMalformed
	}
	signing := parts[0] + "." + parts[1]
	if !hmac.Equal([]byte(sign(secret, signing)), []byte(parts[2])) {
		return nil, ErrBadSignature
	}
	raw, err := b64.DecodeString(parts[1])
	if err != nil {
		return nil, ErrMalformed
	}
	var claims map[string]any
	if err := json.Unmarshal(raw, &claims); err != nil {
		return nil, ErrMalformed
	}
	exp, ok := claims["exp"].(float64)
	if !ok {
		return nil, ErrInvalidClaims
	}
	if now.Unix() >= int64(exp) {
		return nil, ErrExpired
	}
	if iatRaw, present := claims["iat"]; present {
		iat, ok := iatRaw.(float64)
		if !ok || int64(iat) > now.Add(ClockSkew).Unix() {
			return nil, ErrInvalidClaims
		}
	}
	return claims, nil
}

// Mint signs a widget-audience token for one workspace, valid for ttl, with a
// fresh random session id.
func Mint(secret, workspaceID string, ttl time.Duration, now time.Time) (string, error) {
	sid := make([]byte, 16)
	if _, err := rand.Read(sid); err != nil {
		return "", err
	}
	return SignHS256(secret, map[string]any{
		"aud": audWidget,
		"wid": workspaceID,
		"sid": hex.EncodeToString(sid),
		"iat": now.Unix(),
		"exp": now.Add(ttl).Unix(),
	})
}

// Verify checks the signature and aud=widget, and requires exp, iat and a
// workspace: iat not in the future, exp after iat, and a lifetime (exp − iat)
// of at most maxLifetime + ClockSkew, so a leaked signing key's forgeries and
// replayed tokens stay as short-lived as the ones the edge mints. maxLifetime
// <= 0 rejects every token (fail closed).
func Verify(secret, token string, now time.Time, maxLifetime time.Duration) (*Claims, error) {
	claims, err := ParseHS256(secret, token, now)
	if err != nil {
		return nil, err
	}
	if aud, _ := claims["aud"].(string); aud != audWidget {
		return nil, ErrWrongAudience
	}
	iat, hasIat := claims["iat"].(float64)
	exp := claims["exp"].(float64) // ParseHS256 guarantees a numeric exp
	if !hasIat || maxLifetime <= 0 || exp <= iat ||
		time.Duration(exp-iat)*time.Second > maxLifetime+ClockSkew {
		return nil, ErrInvalidClaims
	}
	wid, _ := claims["wid"].(string)
	if wid == "" {
		return nil, ErrInvalidClaims
	}
	sid, _ := claims["sid"].(string)
	return &Claims{Aud: audWidget, WorkspaceID: wid, SessionID: sid, Iat: int64(iat), Exp: int64(exp)}, nil
}

func sign(secret, signing string) string {
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(signing))
	return b64.EncodeToString(mac.Sum(nil))
}
