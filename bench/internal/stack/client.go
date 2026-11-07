// SPDX-License-Identifier: Apache-2.0

// Package stack is the benchmark harnesses' client for a running Raggie stack:
// the control-plane admin API (onboarding, workspaces, documents) and the edge
// chat stream, instrumented with per-phase timings.
package stack

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// Client talks to one stack. Token is the admin access token (aud=admin),
// accepted by both the control-plane and the edge.
type Client struct {
	CP    string // control-plane base URL, e.g. http://127.0.0.1:58000
	Edge  string // edge base URL, e.g. http://localhost:8090
	HTTP  *http.Client
	Token string
}

// NewClient returns a client with a connection-pooling transport sized for
// maxConns concurrent streams (no client-side timeout: every call is bounded
// by its context).
func NewClient(cp, edge string, maxConns int) *Client {
	maxConns = max(maxConns, 16)
	tr := http.DefaultTransport.(*http.Transport).Clone()
	tr.MaxIdleConns = maxConns
	tr.MaxIdleConnsPerHost = maxConns
	tr.MaxConnsPerHost = 0
	tr.ResponseHeaderTimeout = 0
	return &Client{
		CP:   strings.TrimRight(cp, "/"),
		Edge: strings.TrimRight(edge, "/"),
		HTTP: &http.Client{Transport: tr},
	}
}

// APIError is a non-2xx answer from the stack.
type APIError struct {
	Method, URL string
	Status      int
	Code        string // edge/control-plane error code when present
	Body        string // first bytes of the body, for diagnostics
}

func (e *APIError) Error() string {
	if e.Code != "" {
		return fmt.Sprintf("%s %s: HTTP %d (%s)", e.Method, e.URL, e.Status, e.Code)
	}
	return fmt.Sprintf("%s %s: HTTP %d: %s", e.Method, e.URL, e.Status, e.Body)
}

// StatusOf returns the HTTP status of an *APIError, or 0.
func StatusOf(err error) int {
	var ae *APIError
	if errors.As(err, &ae) {
		return ae.Status
	}
	return 0
}

func apiError(req *http.Request, resp *http.Response) error {
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
	var parsed struct {
		Code   string `json:"code"`
		Detail any    `json:"detail"`
	}
	_ = json.Unmarshal(body, &parsed)
	return &APIError{
		Method: req.Method, URL: req.URL.Path, Status: resp.StatusCode,
		Code: parsed.Code, Body: strings.TrimSpace(string(body)),
	}
}

func (c *Client) do(ctx context.Context, method, rawURL string, body io.Reader, contentType string, out any) error {
	req, err := http.NewRequestWithContext(ctx, method, rawURL, body)
	if err != nil {
		return err
	}
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	if c.Token != "" {
		req.Header.Set("Authorization", "Bearer "+c.Token)
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		return apiError(req, resp)
	}
	if out == nil {
		_, _ = io.Copy(io.Discard, resp.Body)
		return nil
	}
	return json.NewDecoder(resp.Body).Decode(out)
}

func (c *Client) doJSON(ctx context.Context, method, rawURL string, in, out any) error {
	var body io.Reader
	if in != nil {
		b, err := json.Marshal(in)
		if err != nil {
			return err
		}
		body = bytes.NewReader(b)
	}
	return c.do(ctx, method, rawURL, body, "application/json", out)
}

// OnboardingState is GET /api/v1/onboarding/state.
type OnboardingState struct {
	Onboarded          bool `json:"onboarded"`
	HasSuperAdmin      bool `json:"has_super_admin"`
	SetupTokenRequired bool `json:"setup_token_required"`
}

func (c *Client) OnboardingState(ctx context.Context) (OnboardingState, error) {
	var s OnboardingState
	err := c.doJSON(ctx, http.MethodGet, c.CP+"/api/v1/onboarding/state", nil, &s)
	return s, err
}

// Bootstrap creates the first super admin on a fresh stack and returns its
// access token.
func (c *Client) Bootstrap(ctx context.Context, email, password, orgName, setupToken string) (string, error) {
	in := map[string]any{"email": email, "password": password, "org_name": orgName}
	if setupToken != "" {
		in["setup_token"] = setupToken
	}
	var out struct {
		AccessToken string `json:"access_token"`
	}
	if err := c.doJSON(ctx, http.MethodPost, c.CP+"/api/v1/onboarding/bootstrap", in, &out); err != nil {
		return "", err
	}
	return out.AccessToken, nil
}

// Login exchanges credentials for an access token.
func (c *Client) Login(ctx context.Context, email, password string) (string, error) {
	var out struct {
		AccessToken string `json:"access_token"`
	}
	err := c.doJSON(ctx, http.MethodPost, c.CP+"/api/v1/auth/login",
		map[string]string{"email": email, "password": password}, &out)
	return out.AccessToken, err
}

// Me is the authenticated user (GET /api/v1/auth/me).
type Me struct {
	ID              string `json:"id"`
	Email           string `json:"email"`
	OrgID           string `json:"org_id"`
	IsPlatformAdmin bool   `json:"is_platform_admin"`
}

func (c *Client) Me(ctx context.Context) (Me, error) {
	var me Me
	err := c.doJSON(ctx, http.MethodGet, c.CP+"/api/v1/auth/me", nil, &me)
	return me, err
}

// Workspace is the subset of a workspace the harnesses need.
type Workspace struct {
	ID   string `json:"id"`
	Name string `json:"name"`
	Type string `json:"type"`
}

// CreateWorkspace creates an INTERNAL workspace in the org.
func (c *Client) CreateWorkspace(ctx context.Context, orgID, name string) (Workspace, error) {
	var ws Workspace
	err := c.doJSON(ctx, http.MethodPost, c.CP+"/api/v1/admin/orgs/"+url.PathEscape(orgID)+"/workspaces",
		map[string]string{"name": name, "type": "INTERNAL"}, &ws)
	return ws, err
}

// Document statuses (control-plane DocumentStatus).
const (
	StatusPending    = "PENDING"
	StatusProcessing = "PROCESSING"
	StatusSuccess    = "SUCCESS"
	StatusFailed     = "FAILED"
)

// Document is the subset of a document row the harnesses need.
type Document struct {
	ID           string    `json:"id"`
	Filename     string    `json:"filename"`
	FileSize     int64     `json:"file_size"`
	Status       string    `json:"status"`
	ErrorMessage string    `json:"error_message"`
	CreatedAt    time.Time `json:"created_at"`
	UpdatedAt    time.Time `json:"updated_at"`
}

// Terminal reports whether ingestion finished (successfully or not).
func (d Document) Terminal() bool { return d.Status == StatusSuccess || d.Status == StatusFailed }

// Upload sends one file through the direct upload path.
func (c *Client) Upload(ctx context.Context, workspaceID, filename string, data []byte) (Document, error) {
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	part, err := mw.CreateFormFile("file", filename)
	if err != nil {
		return Document{}, err
	}
	if _, err := part.Write(data); err != nil {
		return Document{}, err
	}
	if err := mw.Close(); err != nil {
		return Document{}, err
	}
	var doc Document
	err = c.do(ctx, http.MethodPost, c.CP+"/api/v1/admin/workspaces/"+url.PathEscape(workspaceID)+"/documents",
		&buf, mw.FormDataContentType(), &doc)
	return doc, err
}

// Documents lists a workspace's documents.
func (c *Client) Documents(ctx context.Context, workspaceID string) ([]Document, error) {
	var docs []Document
	err := c.doJSON(ctx, http.MethodGet, c.CP+"/api/v1/admin/workspaces/"+url.PathEscape(workspaceID)+"/documents", nil, &docs)
	return docs, err
}

// WaitDocuments polls until every document in ids is terminal (or ctx ends),
// calling onChange on every observed status transition.
func (c *Client) WaitDocuments(ctx context.Context, workspaceID string, ids []string, poll time.Duration,
	onChange func(doc Document, at time.Time)) (map[string]Document, error) {
	want := make(map[string]bool, len(ids))
	for _, id := range ids {
		want[id] = true
	}
	last := make(map[string]Document, len(ids))
	ticker := time.NewTicker(poll)
	defer ticker.Stop()
	for {
		docs, err := c.Documents(ctx, workspaceID)
		if err != nil {
			return last, err
		}
		now := time.Now()
		done := 0
		for _, d := range docs {
			if !want[d.ID] {
				continue
			}
			if prev, seen := last[d.ID]; !seen || prev.Status != d.Status {
				if onChange != nil {
					onChange(d, now)
				}
			}
			last[d.ID] = d
			if d.Terminal() {
				done++
			}
		}
		if done == len(want) {
			return last, nil
		}
		select {
		case <-ctx.Done():
			return last, fmt.Errorf("waiting for %d/%d documents: %w", len(want)-done, len(want), ctx.Err())
		case <-ticker.C:
		}
	}
}
