-- SPDX-License-Identifier: Apache-2.0
-- 0001 created per-org / system LLMaaS columns and defaulted
-- system_settings.llmaas_base_url to 'https://api.llmaas.ai/v1' — a domain this
-- project does not own, so an install that never overrode it could have pointed
-- an API key there. Nothing reads these columns (the LLM endpoint comes from
-- LLMAAS_BASE_URL / LLM_MODEL_PROFILES_JSON in the environment), so drop them.
ALTER TABLE system_settings
    DROP COLUMN IF EXISTS llmaas_base_url,
    DROP COLUMN IF EXISTS llmaas_api_key_ref;
ALTER TABLE organizations
    DROP COLUMN IF EXISTS llmaas_base_url,
    DROP COLUMN IF EXISTS llmaas_api_key_ref;

-- New installs are English-first: the column default follows suit. The control
-- plane always writes the install default (DEFAULT_LOCALE) explicitly; existing
-- users keep the locale they have.
ALTER TABLE users ALTER COLUMN locale SET DEFAULT 'en';

-- Why a streamed BOT answer stopped early, e.g. 'shutdown_drain' when a replica
-- drain cut it off; the edge sets it on finalize and resumes such answers.
-- NULL means the answer completed normally.
ALTER TABLE messages ADD COLUMN IF NOT EXISTS interrupted_reason TEXT;

-- Widget CORS origins are now stored the way browsers serialize the Origin
-- header (the edge compares it byte-for-byte). Rewrite origins saved before
-- that: lowercase, no trailing slash, no leading zeros in the port, no default
-- port (:80 for http, :443 for https), duplicates removed in first-seen order.
-- The old validator only accepted ASCII hosts, so no IDN conversion is needed.
-- Idempotent: already-normalized lists are left untouched.
UPDATE workspaces AS w
   SET cors_allowed_origins = fixed.origins
  FROM (
        SELECT id, jsonb_agg(origin ORDER BY first_pos) AS origins
          FROM (
                SELECT ws.id, n.origin, min(e.pos) AS first_pos
                  FROM (SELECT id, cors_allowed_origins FROM workspaces
                         WHERE jsonb_typeof(cors_allowed_origins) = 'array') AS ws
                 CROSS JOIN LATERAL jsonb_array_elements_text(ws.cors_allowed_origins)
                       WITH ORDINALITY AS e(value, pos)
                 CROSS JOIN LATERAL (
                       SELECT regexp_replace(
                                regexp_replace(
                                  regexp_replace(rtrim(lower(btrim(e.value)), '/'),
                                                 ':0+([0-9])', ':\1'),
                                  '^(https://[^/]+):443$', '\1'),
                                '^(http://[^/]+):80$', '\1') AS origin
                       ) AS n
                 WHERE n.origin <> ''
                 GROUP BY ws.id, n.origin
               ) AS d
         GROUP BY id
       ) AS fixed
 WHERE w.id = fixed.id
   AND w.cors_allowed_origins IS DISTINCT FROM fixed.origins;
