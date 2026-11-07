-- SPDX-License-Identifier: Apache-2.0

ALTER TABLE documents
    DROP COLUMN IF EXISTS error_code,
    DROP COLUMN IF EXISTS error_params;
