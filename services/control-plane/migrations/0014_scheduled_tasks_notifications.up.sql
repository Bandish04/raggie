-- SPDX-License-Identifier: Apache-2.0
-- Scheduled tasks (cron jobs) + an in-app notifications inbox.
--
-- A scheduled task is a prompt the assistant runs on a cron schedule for its
-- owner. A separate scheduler WORKER (not the control plane) polls enabled tasks
-- by next_run_at, calls the edge to execute the prompt, writes a row into
-- notifications, and advances next_run_at. The control plane owns the schema +
-- the user-facing CRUD + the next_run computation; it never executes a task.
--
-- All additive + idempotent (IF NOT EXISTS) so re-runs and a left-applied
-- rollback are safe. The schedule (cron/timezone) is validated at the API layer
-- (croniter); next_run_at is computed there too.

-- Scheduled tasks -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,        -- owner
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    prompt       TEXT NOT NULL,                  -- the task the assistant runs each fire
    cron         TEXT NOT NULL,                  -- standard 5-field cron expression
    timezone     TEXT NOT NULL DEFAULT 'Europe/Istanbul',
    enabled      BOOLEAN NOT NULL DEFAULT true,
    web_search   BOOLEAN NOT NULL DEFAULT false,
    deep_search  BOOLEAN NOT NULL DEFAULT false,
    model        TEXT,                           -- pinned chat model (null = user/default)
    answer_style TEXT,                           -- corporate | short | instructive | balanced
    next_run_at  TIMESTAMPTZ,                    -- when it should next fire (worker polls this)
    last_run_at  TIMESTAMPTZ,                    -- last execution time (worker-maintained)
    last_status  TEXT,                           -- 'ok' | 'error' (worker-maintained)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The scheduler claims due tasks: WHERE enabled AND next_run_at <= now().
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_due
    ON scheduled_tasks(enabled, next_run_at);
-- A user's own task list.
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_user ON scheduled_tasks(user_id);

-- Guard answer_style at the DB layer too (the API also validates). Allowed only
-- when set; NULL means "no pin" (use the user's / default style).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'scheduled_tasks_answer_style_check'
    ) THEN
        ALTER TABLE scheduled_tasks
            ADD CONSTRAINT scheduled_tasks_answer_style_check
            CHECK (answer_style IS NULL
                   OR answer_style IN ('corporate', 'short', 'instructive', 'balanced'));
    END IF;
END$$;

-- Guard last_status similarly: NULL (never run) or one of the two outcomes.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'scheduled_tasks_last_status_check'
    ) THEN
        ALTER TABLE scheduled_tasks
            ADD CONSTRAINT scheduled_tasks_last_status_check
            CHECK (last_status IS NULL OR last_status IN ('ok', 'error'));
    END IF;
END$$;

-- updated_at maintenance (reuses the shared set_updated_at trigger fn).
DROP TRIGGER IF EXISTS trg_scheduled_tasks_updated ON scheduled_tasks;
CREATE TRIGGER trg_scheduled_tasks_updated BEFORE UPDATE ON scheduled_tasks
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Notifications inbox -------------------------------------------------------
-- The worker writes one row per task execution (kind = 'task_result'); the user
-- reads/marks them here. task_id is nullable so a notification survives the
-- deletion of the task that produced it (ON DELETE SET NULL).
CREATE TABLE IF NOT EXISTS notifications (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_id    UUID REFERENCES scheduled_tasks(id) ON DELETE SET NULL,
    kind       TEXT NOT NULL DEFAULT 'task_result',
    title      TEXT NOT NULL,
    body       TEXT NOT NULL,
    is_read    BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The inbox lists a user's notifications newest-first.
CREATE INDEX IF NOT EXISTS idx_notifications_user_created
    ON notifications(user_id, created_at DESC);
-- The unread badge counts a user's unread notifications.
CREATE INDEX IF NOT EXISTS idx_notifications_user_unread
    ON notifications(user_id, is_read);
