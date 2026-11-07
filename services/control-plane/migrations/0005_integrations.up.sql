-- SPDX-License-Identifier: Apache-2.0
-- Generic external-integration / MCP foundation. Provider-agnostic by design:
-- `provider` is free-form (slack, notion, gdrive, a generic MCP server, …) so new
-- connectors are additive. Credentials are stored ENCRYPTED at rest
-- (credentials_enc, Fernet) — never plaintext. An integration is scoped to a
-- user, team, or workspace; synced content lands in target_workspace_id.

CREATE TABLE integrations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    scope_type          TEXT NOT NULL CHECK (scope_type IN ('user', 'team', 'workspace')),
    scope_id            UUID NOT NULL,                 -- user/team/workspace id (validated in app)
    target_workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE,  -- where synced data lands
    provider            TEXT NOT NULL,                 -- 'slack' | 'notion' | 'mcp' | …
    display_name        TEXT,
    status              TEXT NOT NULL DEFAULT 'disconnected'
                        CHECK (status IN ('connected', 'error', 'disconnected', 'syncing')),
    credentials_enc     TEXT,                          -- Fernet-encrypted credential blob (never plaintext)
    config              JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_error          TEXT,
    created_by          UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_integrations_org ON integrations(org_id);
CREATE INDEX idx_integrations_scope ON integrations(scope_type, scope_id);
-- One integration per (scope, provider) — re-connecting updates the existing row.
CREATE UNIQUE INDEX uq_integrations_scope_provider ON integrations(scope_type, scope_id, provider);
CREATE TRIGGER trg_integrations_updated BEFORE UPDATE ON integrations
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Per-source sync cursor (e.g. a Slack channel, a Drive folder) for incremental
-- pulls and for scoping deletion when an integration is disconnected.
CREATE TABLE integration_sync_state (
    integration_id UUID NOT NULL REFERENCES integrations(id) ON DELETE CASCADE,
    source_ref     TEXT NOT NULL,
    cursor         TEXT,
    last_synced_at TIMESTAMPTZ,
    document_count INT NOT NULL DEFAULT 0,
    PRIMARY KEY (integration_id, source_ref)
);

-- Provenance on documents so synced content is scoped + deletable, and citations
-- can show their origin. Default 'upload' keeps existing rows correct.
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS provider       TEXT NOT NULL DEFAULT 'upload',
    ADD COLUMN IF NOT EXISTS integration_id UUID REFERENCES integrations(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS source_ref     TEXT;
CREATE INDEX IF NOT EXISTS idx_documents_integration ON documents(integration_id);
