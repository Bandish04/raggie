-- SPDX-License-Identifier: Apache-2.0
-- Per-message evaluation evidence. Conversation-level fields remain the compact
-- admin queue projection; detailed faithfulness/citation metrics live on BOT
-- messages so each flag is explainable and auditable.
ALTER TABLE messages ADD COLUMN IF NOT EXISTS evaluation_score REAL;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS faithfulness_score REAL;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS citation_validity_score REAL;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS citation_coverage_score REAL;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS evaluation_flagged BOOLEAN;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS evaluation_json JSONB;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS evaluated_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_messages_evaluation_flagged
    ON messages(conversation_id, evaluation_score)
    WHERE evaluation_flagged = TRUE;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'messages_evaluation_scores_check'
    ) THEN
        ALTER TABLE messages
            ADD CONSTRAINT messages_evaluation_scores_check CHECK (
                (evaluation_score IS NULL OR evaluation_score BETWEEN 0 AND 1)
                AND (faithfulness_score IS NULL OR faithfulness_score BETWEEN 0 AND 1)
                AND (citation_validity_score IS NULL
                     OR citation_validity_score BETWEEN 0 AND 1)
                AND (citation_coverage_score IS NULL
                     OR citation_coverage_score BETWEEN 0 AND 1)
            );
    END IF;
END$$;
