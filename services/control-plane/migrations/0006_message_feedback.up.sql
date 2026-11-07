-- SPDX-License-Identifier: Apache-2.0
-- Per-message thumbs up/down feedback. A 👎 also flags the conversation
-- (is_flagged) so it surfaces in the existing flagged-review queue. One vote per
-- (message, user); re-voting overwrites.
CREATE TABLE message_feedback (
    message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    user_id    UUID REFERENCES users(id) ON DELETE SET NULL,
    rating     TEXT NOT NULL CHECK (rating IN ('up', 'down')),
    comment    TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (message_id, user_id)
);
CREATE INDEX idx_message_feedback_rating ON message_feedback(rating);
