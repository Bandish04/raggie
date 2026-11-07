-- SPDX-License-Identifier: Apache-2.0

DROP INDEX IF EXISTS idx_messages_evaluation_flagged;
ALTER TABLE messages DROP CONSTRAINT IF EXISTS messages_evaluation_scores_check;
ALTER TABLE messages DROP COLUMN IF EXISTS evaluated_at;
ALTER TABLE messages DROP COLUMN IF EXISTS evaluation_json;
ALTER TABLE messages DROP COLUMN IF EXISTS evaluation_flagged;
ALTER TABLE messages DROP COLUMN IF EXISTS citation_coverage_score;
ALTER TABLE messages DROP COLUMN IF EXISTS citation_validity_score;
ALTER TABLE messages DROP COLUMN IF EXISTS faithfulness_score;
ALTER TABLE messages DROP COLUMN IF EXISTS evaluation_score;
