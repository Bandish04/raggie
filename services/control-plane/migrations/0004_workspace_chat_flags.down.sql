-- SPDX-License-Identifier: Apache-2.0

ALTER TABLE workspaces
    DROP COLUMN IF EXISTS personalization_enabled,
    DROP COLUMN IF EXISTS web_search_enabled;
