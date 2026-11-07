-- SPDX-License-Identifier: Apache-2.0
-- Add an 'org' scope to integrations. MCP/tool providers (Jira, MCP servers) are
-- ORG-WIDE capabilities the assistant uses everywhere — not per-workspace data
-- sources — so they connect once at the org level (scope_type='org',
-- scope_id=org_id, target_workspace_id=NULL). Data-source providers (Slack,
-- Drive) stay user/team/workspace-scoped. The edge's Jira gate keys on an
-- org-level row with provider='jira' AND status='connected'.
--
-- The original CHECK was created inline in 0005 with a server-generated name, so
-- look it up by definition (matches '%scope_type%') rather than assuming a name,
-- then re-add it widened to include 'org'. Idempotent + safe to re-run.

DO $$
DECLARE cname text;
BEGIN
    SELECT conname INTO cname FROM pg_constraint
     WHERE conrelid = 'integrations'::regclass AND contype = 'c'
       AND pg_get_constraintdef(oid) ILIKE '%scope_type%';
    IF cname IS NOT NULL THEN
        EXECUTE format('ALTER TABLE integrations DROP CONSTRAINT %I', cname);
    END IF;
END $$;

ALTER TABLE integrations ADD CONSTRAINT integrations_scope_type_check
    CHECK (scope_type IN ('user', 'team', 'workspace', 'org'));
