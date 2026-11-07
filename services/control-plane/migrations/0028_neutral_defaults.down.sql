-- SPDX-License-Identifier: Apache-2.0

ALTER TABLE users ALTER COLUMN timezone SET DEFAULT 'Europe/Istanbul';
ALTER TABLE scheduled_tasks ALTER COLUMN timezone SET DEFAULT 'Europe/Istanbul';
