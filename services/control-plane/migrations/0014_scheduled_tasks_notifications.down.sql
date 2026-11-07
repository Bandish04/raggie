-- SPDX-License-Identifier: Apache-2.0
-- Reverse 0014: drop the notifications inbox + scheduled_tasks (their triggers,
-- indexes and constraints go with the tables). notifications is dropped first
-- because of its FK to scheduled_tasks.
DROP TABLE IF EXISTS notifications;
DROP TABLE IF EXISTS scheduled_tasks;
