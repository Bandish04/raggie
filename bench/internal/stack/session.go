// SPDX-License-Identifier: Apache-2.0

package stack

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// Config locates a stack and the admin identity the harness acts as.
type Config struct {
	CPURL      string
	EdgeURL    string
	SetupToken string // only needed to bootstrap a fresh stack
	Email      string // explicit credentials win over saved state
	Password   string
	StateDir   string // where generated credentials are remembered
	RepoRoot   string // to reuse the web e2e suite's saved onboarding state
	MaxConns   int
}

// ConfigFromEnv reads RAGGIE_BENCH_* (falling back to the E2E_* exports of
// scripts/e2e-stack.sh and its default host ports).
func ConfigFromEnv(repoRoot string) Config {
	stateDir := os.Getenv("RAGGIE_BENCH_DIR")
	if stateDir == "" {
		if cache, err := os.UserCacheDir(); err == nil {
			stateDir = filepath.Join(cache, "raggie-bench")
		}
	}
	return Config{
		CPURL:      firstEnv("http://127.0.0.1:58000", "RAGGIE_BENCH_CONTROL_PLANE_URL", "E2E_CONTROL_PLANE_URL"),
		EdgeURL:    firstEnv("http://localhost:8090", "RAGGIE_BENCH_EDGE_URL", "E2E_EDGE_URL"),
		SetupToken: firstEnv("", "RAGGIE_BENCH_SETUP_TOKEN", "E2E_SETUP_TOKEN"),
		Email:      os.Getenv("RAGGIE_BENCH_EMAIL"),
		Password:   os.Getenv("RAGGIE_BENCH_PASSWORD"),
		StateDir:   stateDir,
		RepoRoot:   repoRoot,
	}
}

func firstEnv(def string, keys ...string) string {
	for _, k := range keys {
		if v := strings.TrimSpace(os.Getenv(k)); v != "" {
			return v
		}
	}
	return def
}

// Session is an authenticated client plus the admin's identity.
type Session struct {
	*Client
	Me Me
	// Bootstrapped is true when this run created the first admin.
	Bootstrapped bool
}

type savedCredentials struct {
	CPURL    string `json:"control_plane_url"`
	Email    string `json:"email"`
	Password string `json:"password"`
}

// Connect authenticates against the stack. On a fresh stack (no super admin)
// it bootstraps one with generated credentials and remembers them in
// StateDir; otherwise it logs in with, in order: explicit credentials, the
// remembered ones for this control-plane URL, or the web e2e suite's saved
// onboarding state (web/e2e/stack/.state/stack.json).
func Connect(ctx context.Context, cfg Config) (*Session, error) {
	c := NewClient(cfg.CPURL, cfg.EdgeURL, cfg.MaxConns)
	state, err := c.OnboardingState(ctx)
	if err != nil {
		return nil, fmt.Errorf("control plane unreachable at %s: %w", cfg.CPURL, err)
	}
	s := &Session{Client: c}
	if !state.HasSuperAdmin {
		if state.SetupTokenRequired && cfg.SetupToken == "" {
			return nil, errors.New("fresh stack needs a setup token: set RAGGIE_BENCH_SETUP_TOKEN (or eval \"$(scripts/e2e-stack.sh env)\")")
		}
		creds := savedCredentials{CPURL: cfg.CPURL, Email: "bench-admin@bench.raggie.test", Password: "Bench-" + randomHex(16)}
		if cfg.Email != "" && cfg.Password != "" {
			creds.Email, creds.Password = cfg.Email, cfg.Password
		}
		token, err := c.Bootstrap(ctx, creds.Email, creds.Password, "Raggie Bench", cfg.SetupToken)
		if err != nil {
			return nil, fmt.Errorf("bootstrap first admin: %w", err)
		}
		if err := saveCredentials(cfg.StateDir, creds); err != nil {
			return nil, fmt.Errorf("remember generated admin credentials: %w", err)
		}
		c.Token, s.Bootstrapped = token, true
	} else {
		email, password, err := resolveCredentials(cfg)
		if err != nil {
			return nil, err
		}
		if c.Token, err = c.Login(ctx, email, password); err != nil {
			return nil, fmt.Errorf("login as %s: %w", email, err)
		}
	}
	if s.Me, err = c.Me(ctx); err != nil {
		return nil, fmt.Errorf("resolve admin identity: %w", err)
	}
	return s, nil
}

func resolveCredentials(cfg Config) (string, string, error) {
	if cfg.Email != "" && cfg.Password != "" {
		return cfg.Email, cfg.Password, nil
	}
	if saved, err := loadCredentials(cfg.StateDir); err == nil && saved.CPURL == cfg.CPURL {
		return saved.Email, saved.Password, nil
	}
	if cfg.RepoRoot != "" {
		path := filepath.Join(cfg.RepoRoot, "web", "e2e", "stack", ".state", "stack.json")
		if b, err := os.ReadFile(path); err == nil { // #nosec G304 -- fixed repo-relative path
			var st struct {
				AdminEmail    string `json:"adminEmail"`
				AdminPassword string `json:"adminPassword"`
			}
			if json.Unmarshal(b, &st) == nil && st.AdminEmail != "" {
				return st.AdminEmail, st.AdminPassword, nil
			}
		}
	}
	return "", "", errors.New("stack is already onboarded: set RAGGIE_BENCH_EMAIL and RAGGIE_BENCH_PASSWORD to a super admin")
}

func credentialsPath(dir string) string { return filepath.Join(dir, "admin.json") }

func saveCredentials(dir string, c savedCredentials) error {
	if dir == "" {
		return errors.New("no state dir (set RAGGIE_BENCH_DIR)")
	}
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	// The generated admin password is persisted on purpose (mode 0600, in the
	// operator's own state dir) so later runs can log in to the stack it bootstrapped.
	b, _ := json.MarshalIndent(c, "", "  ") // #nosec G117 -- see above
	return os.WriteFile(credentialsPath(dir), b, 0o600)
}

func loadCredentials(dir string) (savedCredentials, error) {
	var c savedCredentials
	b, err := os.ReadFile(credentialsPath(dir)) // #nosec G304 -- operator-chosen state dir
	if err != nil {
		return c, err
	}
	err = json.Unmarshal(b, &c)
	return c, err
}

func randomHex(n int) string {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		panic(err) // crypto/rand never fails on supported platforms
	}
	return hex.EncodeToString(b)
}
