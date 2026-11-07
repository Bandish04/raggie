-- SPDX-License-Identifier: Apache-2.0
-- One re-embed / restore re-index at a time across replicas. A lease row
-- (owner token + expiry, refreshed while the run lasts) replaces the session
-- advisory lock, which a transaction pooler (PgBouncer pool_mode=transaction)
-- breaks: lock and unlock can reach different backends.
ALTER TABLE system_settings
    ADD COLUMN IF NOT EXISTS reembed_lease_owner TEXT,
    ADD COLUMN IF NOT EXISTS reembed_lease_expires_at TIMESTAMPTZ;
