-- SPDX-License-Identifier: Apache-2.0
-- Durable user memory (0007) is a chat-intelligence feature like web search and
-- personalization, and gets the same double gate: the MEMORY_ENABLED kill switch
-- (edge + control-plane, default on) AND this per-workspace flag. Memory facts
-- are mined from — and injected into — prompts sent to the external LLM, so the
-- flag defaults OFF, including for every existing workspace (privacy-first):
-- admins opt each workspace in.
ALTER TABLE workspaces
    ADD COLUMN IF NOT EXISTS memory_enabled BOOLEAN NOT NULL DEFAULT FALSE;
