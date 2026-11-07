-- SPDX-License-Identifier: Apache-2.0
-- Reverse 0015: narrow the scope_type CHECK back to user/team/workspace. Any
-- org-scoped rows would violate the narrowed constraint, so delete them first
-- (mirrors the up's by-definition constraint lookup so the name need not match).

DELETE FROM integrations WHERE scope_type = 'org';

DO $$
DECLARE cname text;
BEGIN
    SELECT conname INTO cname FROM pg_constraint
     WHERE conrelid = 'integrations'::regclass AND contype = 'c'
       AND pg_get_constraintdef(oid) ILIKE '%scope_type%';
    IF cname IS NOT NULL THEN
        EXECUTE format('ALTER TABLE integrations DROP CONSTRAINT %I', cname);
    END IF;
END $$;

ALTER TABLE integrations ADD CONSTRAINT integrations_scope_type_check
    CHECK (scope_type IN ('user', 'team', 'workspace'));
