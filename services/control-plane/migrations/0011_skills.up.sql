-- SPDX-License-Identifier: Apache-2.0
-- Skills: reusable assistant presets a user invokes in chat via a slash-command.
--
-- A skill bundles a name + slash keyword (slug) + instructions, plus an optional
-- pinned model and answer_style. The WEB app applies a skill by mapping it onto
-- the EXISTING chat request fields (system_prompt = instructions, model = model,
-- answer_style = answer_style) — the Go edge already injects all three, so no
-- edge change is needed. Org-scoped; the slug is unique per org so it can be
-- typed unambiguously in chat. All additive + idempotent (IF NOT EXISTS) so
-- re-runs and a left-applied rollback are safe.
CREATE TABLE IF NOT EXISTS skills (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_by   UUID REFERENCES users(id) ON DELETE SET NULL,
    name         TEXT NOT NULL,
    slug         TEXT NOT NULL,                 -- slash-command keyword (e.g. "ozet")
    description  TEXT,
    instructions TEXT NOT NULL,                 -- becomes the chat system_prompt
    icon         TEXT,                          -- Material Symbols name (nullable)
    model        TEXT,                          -- pinned chat model (null = user/default)
    answer_style TEXT,                          -- corporate | short | instructive | balanced
    enabled      BOOLEAN NOT NULL DEFAULT true,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One slug per org so the chat picker / typed command resolves unambiguously.
CREATE UNIQUE INDEX IF NOT EXISTS uq_skills_org_slug ON skills(org_id, slug);
-- The chat skill picker lists enabled skills for an org.
CREATE INDEX IF NOT EXISTS idx_skills_org_enabled ON skills(org_id, enabled);

-- Guard answer_style at the DB layer too (the API also validates). Allowed only
-- when set; NULL means "no pin" (use the user's / default style).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'skills_answer_style_check'
    ) THEN
        ALTER TABLE skills
            ADD CONSTRAINT skills_answer_style_check
            CHECK (answer_style IS NULL
                   OR answer_style IN ('corporate', 'short', 'instructive', 'balanced'));
    END IF;
END$$;

-- updated_at maintenance (reuses the shared set_updated_at trigger fn).
DROP TRIGGER IF EXISTS trg_skills_updated ON skills;
CREATE TRIGGER trg_skills_updated BEFORE UPDATE ON skills
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
