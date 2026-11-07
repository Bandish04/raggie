-- SPDX-License-Identifier: Apache-2.0

ALTER TABLE system_settings
    DROP COLUMN IF EXISTS brand_icon_type,
    DROP COLUMN IF EXISTS brand_icon_key,
    DROP COLUMN IF EXISTS brand_logo_type,
    DROP COLUMN IF EXISTS brand_logo_key,
    DROP COLUMN IF EXISTS brand_color,
    DROP COLUMN IF EXISTS brand_tagline,
    DROP COLUMN IF EXISTS brand_name;
