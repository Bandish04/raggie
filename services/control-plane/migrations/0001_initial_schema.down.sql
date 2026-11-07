-- SPDX-License-Identifier: Apache-2.0
-- Reverse of 0001_initial_schema.up.sql (drop in dependency order).
DROP TABLE IF EXISTS audit_log;
DROP TABLE IF EXISTS invites;
DROP TABLE IF EXISTS messages;
DROP TABLE IF EXISTS conversations;
DROP TABLE IF EXISTS documents;
DROP TABLE IF EXISTS workspace_members;
DROP TABLE IF EXISTS workspaces;
DROP TABLE IF EXISTS team_members;
DROP TABLE IF EXISTS team_closure;
DROP TABLE IF EXISTS teams;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS organizations;
DROP TABLE IF EXISTS system_settings;
DROP FUNCTION IF EXISTS set_updated_at();
