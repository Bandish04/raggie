-- SPDX-License-Identifier: Apache-2.0
-- Per-workspace chat-intelligence toggles. Both default OFF because they send
-- data OUTSIDE the on-prem boundary: personalization puts the asker's profile in
-- the (external) LLM prompt; web search sends the query to Brave. An admin opts
-- a workspace in explicitly. Idempotent so re-runs are safe.
ALTER TABLE workspaces
    ADD COLUMN IF NOT EXISTS web_search_enabled      BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS personalization_enabled BOOLEAN NOT NULL DEFAULT false;
