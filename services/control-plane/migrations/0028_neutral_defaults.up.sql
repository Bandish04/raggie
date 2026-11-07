-- SPDX-License-Identifier: Apache-2.0
-- Neutral defaults for a public release: new users and scheduled tasks that do
-- not pick a timezone get UTC instead of a country-specific zone. The web
-- pre-fills the browser's zone; the API falls back to DEFAULT_TIMEZONE. Only
-- the column defaults change: existing rows keep the timezone they have.
ALTER TABLE users ALTER COLUMN timezone SET DEFAULT 'UTC';
ALTER TABLE scheduled_tasks ALTER COLUMN timezone SET DEFAULT 'UTC';
