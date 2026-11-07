-- SPDX-License-Identifier: Apache-2.0
-- Enterprise skill governance:
--   * immutable execution-policy snapshots
--   * deterministic SHA-256 policy hashes
--   * explicit external-tool allow-lists (default deny)
--   * message-level audit fields for the policy/model used by a BOT turn
CREATE EXTENSION IF NOT EXISTS pgcrypto;

ALTER TABLE skills ADD COLUMN IF NOT EXISTS allowed_tools TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE skills ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE skills ADD COLUMN IF NOT EXISTS policy_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE skills ADD COLUMN IF NOT EXISTS updated_by UUID
    REFERENCES users(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS skill_versions (
    skill_id       UUID NOT NULL,
    version        INTEGER NOT NULL,
    org_id         UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    owner_user_id  UUID REFERENCES users(id) ON DELETE SET NULL,
    name           TEXT NOT NULL,
    slug           TEXT NOT NULL,
    instructions   TEXT NOT NULL,
    model          TEXT,
    answer_style   TEXT,
    allowed_tools  TEXT[] NOT NULL DEFAULT '{}',
    policy_hash    TEXT NOT NULL,
    created_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (skill_id, version)
);

CREATE INDEX IF NOT EXISTS idx_skill_versions_org_skill
    ON skill_versions(org_id, skill_id, version DESC);

CREATE OR REPLACE FUNCTION skill_execution_policy_hash(
    p_instructions TEXT,
    p_model TEXT,
    p_answer_style TEXT,
    p_allowed_tools TEXT[]
) RETURNS TEXT AS $$
    SELECT encode(
        digest(
            jsonb_build_object(
                'instructions', p_instructions,
                'model', p_model,
                'answer_style', p_answer_style,
                'allowed_tools', to_jsonb(COALESCE(p_allowed_tools, '{}'::TEXT[]))
            )::TEXT,
            'sha256'
        ),
        'hex'
    );
$$ LANGUAGE SQL IMMUTABLE;

-- Backfill every existing mutable skill as immutable version 1 before triggers
-- are enabled. Existing skills default to no external tools.
UPDATE skills
SET version = GREATEST(version, 1),
    policy_hash = skill_execution_policy_hash(
        instructions, model, answer_style, allowed_tools
    )
WHERE policy_hash = ''
   OR policy_hash IS NULL;

INSERT INTO skill_versions (
    skill_id, version, org_id, owner_user_id, name, slug, instructions,
    model, answer_style, allowed_tools, policy_hash, created_by, created_at
)
SELECT
    id, version, org_id, owner_user_id, name, slug, instructions,
    model, answer_style, allowed_tools, policy_hash, created_by, created_at
FROM skills
ON CONFLICT (skill_id, version) DO NOTHING;

CREATE OR REPLACE FUNCTION version_skill_execution_policy() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.version := GREATEST(COALESCE(NEW.version, 1), 1);
        NEW.policy_hash := skill_execution_policy_hash(
            NEW.instructions, NEW.model, NEW.answer_style, NEW.allowed_tools
        );
    ELSIF ROW(NEW.instructions, NEW.model, NEW.answer_style, NEW.allowed_tools)
          IS DISTINCT FROM
          ROW(OLD.instructions, OLD.model, OLD.answer_style, OLD.allowed_tools) THEN
        NEW.version := OLD.version + 1;
        NEW.policy_hash := skill_execution_policy_hash(
            NEW.instructions, NEW.model, NEW.answer_style, NEW.allowed_tools
        );
    ELSIF NEW.policy_hash = '' OR NEW.policy_hash IS NULL THEN
        NEW.policy_hash := skill_execution_policy_hash(
            NEW.instructions, NEW.model, NEW.answer_style, NEW.allowed_tools
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION snapshot_skill_execution_policy() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO skill_versions (
            skill_id, version, org_id, owner_user_id, name, slug, instructions,
            model, answer_style, allowed_tools, policy_hash, created_by
        ) VALUES (
            NEW.id, NEW.version, NEW.org_id, NEW.owner_user_id, NEW.name, NEW.slug,
            NEW.instructions, NEW.model, NEW.answer_style, NEW.allowed_tools,
            NEW.policy_hash, COALESCE(NEW.updated_by, NEW.created_by)
        )
        ON CONFLICT (skill_id, version) DO NOTHING;
    ELSIF NEW.version IS DISTINCT FROM OLD.version THEN
        INSERT INTO skill_versions (
            skill_id, version, org_id, owner_user_id, name, slug, instructions,
            model, answer_style, allowed_tools, policy_hash, created_by
        ) VALUES (
            NEW.id, NEW.version, NEW.org_id, NEW.owner_user_id, NEW.name, NEW.slug,
            NEW.instructions, NEW.model, NEW.answer_style, NEW.allowed_tools,
            NEW.policy_hash, COALESCE(NEW.updated_by, NEW.created_by)
        )
        ON CONFLICT (skill_id, version) DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_skills_version_policy ON skills;
CREATE TRIGGER trg_skills_version_policy
    BEFORE INSERT OR UPDATE OF instructions, model, answer_style, allowed_tools
    ON skills
    FOR EACH ROW EXECUTE FUNCTION version_skill_execution_policy();

DROP TRIGGER IF EXISTS trg_skills_snapshot_policy ON skills;
CREATE TRIGGER trg_skills_snapshot_policy
    AFTER INSERT OR UPDATE OF instructions, model, answer_style, allowed_tools
    ON skills
    FOR EACH ROW EXECUTE FUNCTION snapshot_skill_execution_policy();

ALTER TABLE messages ADD COLUMN IF NOT EXISTS skill_id UUID;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS skill_version INTEGER;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS skill_policy_hash TEXT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS model_used TEXT;

CREATE INDEX IF NOT EXISTS idx_messages_skill_audit
    ON messages(skill_id, skill_version)
    WHERE skill_id IS NOT NULL;
