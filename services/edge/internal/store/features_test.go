// SPDX-License-Identifier: Apache-2.0

package store

import (
	"context"
	"errors"
	"fmt"
	"os"
	"testing"

	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Before control-plane migration 0027 the memory_enabled column does not exist:
// only that error (SQLSTATE 42703 undefined_column) triggers the legacy query.
func TestIsUndefinedColumn(t *testing.T) {
	if !isUndefinedColumn(fmt.Errorf("query: %w", &pgconn.PgError{Code: "42703"})) {
		t.Fatal("wrapped 42703 must be recognised")
	}
	for _, err := range []error{nil, errors.New("boom"), &pgconn.PgError{Code: "42P01"}} {
		if isUndefinedColumn(err) {
			t.Fatalf("%v misread as undefined column", err)
		}
	}
}

// Live Postgres test (CI); skipped unless DATABASE_URL is set. Needs the schema
// with control-plane migration 0027.
func TestWorkspaceFeaturesReadsMemoryFlag(t *testing.T) {
	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		t.Skip("DATABASE_URL not set")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	var orgID, wsID string
	if err := pool.QueryRow(ctx,
		"INSERT INTO organizations(name) VALUES('edge-memory-flag') RETURNING id::text").Scan(&orgID); err != nil {
		t.Fatal(err)
	}
	cleanupOrg(t, pool, orgID)
	if err := pool.QueryRow(ctx,
		"INSERT INTO workspaces(org_id,name,type) VALUES($1::uuid,'ws','INTERNAL') RETURNING id::text",
		orgID).Scan(&wsID); err != nil {
		t.Fatal(err)
	}
	st, err := New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer st.Close()

	f, err := st.WorkspaceFeatures(ctx, wsID)
	if err != nil {
		t.Fatal(err)
	}
	if f.Memory {
		t.Fatal("memory_enabled must default to false (privacy-first)")
	}
	if _, err := pool.Exec(ctx,
		"UPDATE workspaces SET memory_enabled = true, web_search_enabled = true WHERE id = $1::uuid", wsID); err != nil {
		t.Fatal(err)
	}
	f, err = st.WorkspaceFeatures(ctx, wsID)
	if err != nil || !f.Memory || !f.WebSearch || f.Personalization {
		t.Fatalf("flags = %+v, err %v", f, err)
	}
}
