-- SPDX-License-Identifier: Apache-2.0

DROP INDEX IF EXISTS idx_messages_skill_audit;
ALTER TABLE messages DROP COLUMN IF EXISTS model_used;
ALTER TABLE messages DROP COLUMN IF EXISTS skill_policy_hash;
ALTER TABLE messages DROP COLUMN IF EXISTS skill_version;
ALTER TABLE messages DROP COLUMN IF EXISTS skill_id;

DROP TRIGGER IF EXISTS trg_skills_snapshot_policy ON skills;
DROP TRIGGER IF EXISTS trg_skills_version_policy ON skills;
DROP FUNCTION IF EXISTS snapshot_skill_execution_policy();
DROP FUNCTION IF EXISTS version_skill_execution_policy();
DROP FUNCTION IF EXISTS skill_execution_policy_hash(TEXT, TEXT, TEXT, TEXT[]);

DROP TABLE IF EXISTS skill_versions;
ALTER TABLE skills DROP COLUMN IF EXISTS updated_by;
ALTER TABLE skills DROP COLUMN IF EXISTS policy_hash;
ALTER TABLE skills DROP COLUMN IF EXISTS version;
ALTER TABLE skills DROP COLUMN IF EXISTS allowed_tools;
