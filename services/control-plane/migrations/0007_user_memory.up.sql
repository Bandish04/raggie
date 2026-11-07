-- SPDX-License-Identifier: Apache-2.0
-- Durable per-user memory: short facts the assistant learned about a user across
-- conversations (name, role, preferences…), so a new chat already "knows" them.
-- Auto-extracted after a turn (opt-in, MEMORY_ENABLED) and viewable/clearable by
-- the user from Account settings. PK dedups identical facts per user.
CREATE TABLE user_memory (
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, content)
);
CREATE INDEX idx_user_memory_user ON user_memory(user_id, created_at DESC);
