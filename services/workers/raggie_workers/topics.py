# SPDX-License-Identifier: Apache-2.0

"""Event bus topic + consumer-group names (shared across producers/consumers)."""

DOCUMENT_UPLOADED = "raggie.document.uploaded"
DOCUMENT_PROCESSED = "raggie.document.processed"
DOCUMENT_FAILED = "raggie.document.failed"
DOCUMENT_DELETED = "raggie.document.deleted"
CHAT_COMPLETED = "raggie.chat.completed"

INGESTION_GROUP = "ingestion-workers"
EVAL_GROUP = "eval-workers"
