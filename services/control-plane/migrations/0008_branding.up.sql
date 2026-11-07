-- SPDX-License-Identifier: Apache-2.0
-- White-label branding (platform-wide, on the system_settings singleton).
-- SUPER_ADMIN sets the product name, tagline, accent color, and logo/icon
-- (stored in MinIO; only the object key + content-type live here). A public
-- /branding endpoint serves these so the login page is branded too.
ALTER TABLE system_settings
    ADD COLUMN IF NOT EXISTS brand_name        TEXT NOT NULL DEFAULT 'Raggie',
    ADD COLUMN IF NOT EXISTS brand_tagline     TEXT,
    ADD COLUMN IF NOT EXISTS brand_color       TEXT NOT NULL DEFAULT '#0a5bff',
    ADD COLUMN IF NOT EXISTS brand_logo_key    TEXT,
    ADD COLUMN IF NOT EXISTS brand_logo_type   TEXT,
    ADD COLUMN IF NOT EXISTS brand_icon_key    TEXT,
    ADD COLUMN IF NOT EXISTS brand_icon_type   TEXT;
