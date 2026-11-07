# SPDX-License-Identifier: Apache-2.0

"""Domain models (Pydantic) for the control plane.

These mirror the SQL schema columns. Pydantic ignores extra columns by default,
so repository rows (e.g. including ``password_hash``) map cleanly onto the public
models without leaking sensitive fields.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class Role(StrEnum):
    SUPER_ADMIN = "SUPER_ADMIN"
    WORKSPACE_ADMIN = "WORKSPACE_ADMIN"
    STAFF = "STAFF"


class WorkspaceType(StrEnum):
    INTERNAL = "INTERNAL"
    EXTERNAL = "EXTERNAL"


def _default_timezone() -> str:
    from raggie_control_plane.config import settings

    return settings.default_timezone


class DocumentStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    ARCHIVED = "ARCHIVED"


class Organization(BaseModel):
    id: UUID
    name: str
    monthly_token_quota: int | None = None
    created_at: datetime
    updated_at: datetime


class User(BaseModel):
    id: UUID
    org_id: UUID | None = None
    email: str
    role: Role
    # Platform operator (0024). SUPER_ADMIN is org-scoped; only this flag grants
    # cross-org / platform-wide authority (orgs, global settings, operator MCP).
    is_platform_admin: bool = False
    is_active: bool = True
    auth_provider: str = "local"  # local | oidc | saml | scim
    external_id: str | None = None  # SCIM externalId / IdP subject
    # Rich LDAP-like profile (0003). All nullable; power chat personalization.
    full_name: str | None = None
    job_title: str | None = None
    department: str | None = None
    department_id: UUID | None = None  # managed directory link (0009)
    manager_user_id: UUID | None = None
    hire_date: date | None = None  # tenure is computed at read time, never stored
    phone: str | None = None
    location: str | None = None
    location_id: UUID | None = None  # managed directory link (0009)
    timezone: str = Field(default_factory=_default_timezone)
    locale: str = "en"
    # Per-user chat preferences (0010). answer_style tunes the persona; a user may
    # pin a preferred model from the admin-allowed set (NULL = use platform default).
    answer_style: str = "balanced"
    preferred_chat_model: str | None = None
    must_change_password: bool = False
    created_at: datetime
    updated_at: datetime
    # password_hash is intentionally excluded from the public model.


class Department(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    owner_user_id: UUID | None = None  # lead; display-only metadata, no RBAC
    parent_department_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class Location(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    city: str | None = None
    country: str | None = None
    created_at: datetime
    updated_at: datetime


class Skill(BaseModel):
    """A reusable, server-resolved assistant execution policy."""

    id: UUID
    org_id: UUID
    created_by: UUID | None = None
    # owner_user_id NULL = org/published (admin-managed); non-null = a user's
    # personal skill. visibility mirrors that intent ('org' | 'personal'). (0013)
    owner_user_id: UUID | None = None
    visibility: str = "org"
    name: str
    slug: str
    description: str | None = None
    instructions: str
    icon: str | None = None  # Material Symbols name
    model: str | None = None
    answer_style: str | None = None  # corporate | short | instructive | balanced
    allowed_tools: list[str] = Field(default_factory=list)
    version: int = 1
    policy_hash: str = ""
    enabled: bool = True
    created_at: datetime
    updated_at: datetime


class SkillVersion(BaseModel):
    """An immutable execution-policy snapshot used for audit and rollback."""

    skill_id: UUID
    version: int
    org_id: UUID
    owner_user_id: UUID | None = None
    name: str
    slug: str
    instructions: str
    model: str | None = None
    answer_style: str | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    policy_hash: str
    created_by: UUID | None = None
    created_at: datetime


class ScheduledTask(BaseModel):
    """A cron job (0014): a prompt the assistant runs on a schedule for its owner.
    A separate scheduler WORKER polls next_run_at, calls the edge to execute the
    prompt, writes a notification, and advances next_run_at — the control plane
    owns only the schema + CRUD + next-run computation. model/answer_style are
    nullable pins (NULL = use the user's / platform default)."""

    id: UUID
    org_id: UUID
    user_id: UUID  # owner
    workspace_id: UUID
    name: str
    prompt: str
    cron: str  # standard 5-field cron expression
    timezone: str = Field(default_factory=_default_timezone)
    enabled: bool = True
    web_search: bool = False
    deep_search: bool = False
    model: str | None = None
    answer_style: str | None = None  # corporate | short | instructive | balanced
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    last_status: str | None = None  # ok | error (worker-maintained)
    created_at: datetime
    updated_at: datetime


class Notification(BaseModel):
    """An in-app inbox item (0014). The scheduler worker writes one per task
    execution (kind = 'task_result'); the owner reads/marks them. task_id is
    nullable so a notification survives the deletion of its task."""

    id: UUID
    org_id: UUID
    user_id: UUID
    task_id: UUID | None = None
    kind: str = "task_result"
    title: str
    body: str
    is_read: bool = False
    created_at: datetime


class Team(BaseModel):
    id: UUID
    org_id: UUID
    parent_team_id: UUID | None = None
    name: str
    head_user_id: UUID | None = None  # lead; display-only (0009)
    display_order: int = 0
    created_at: datetime


class Workspace(BaseModel):
    id: UUID
    org_id: UUID
    team_id: UUID | None = None
    name: str
    type: WorkspaceType
    system_prompt: str
    temperature: float
    widget_primary_color: str
    cors_allowed_origins: list[str]
    web_search_enabled: bool = False
    personalization_enabled: bool = False
    memory_enabled: bool = False  # durable user memory, per workspace (0027)
    created_at: datetime
    updated_at: datetime


class Invite(BaseModel):
    id: UUID
    org_id: UUID
    email: str
    role: Role
    team_id: UUID | None = None
    workspace_id: UUID | None = None
    full_name: str | None = None
    job_title: str | None = None
    department: str | None = None
    department_id: UUID | None = None  # managed directory link (0009)
    manager_user_id: UUID | None = None
    phone: str | None = None
    location: str | None = None
    location_id: UUID | None = None  # managed directory link (0009)
    timezone: str | None = None
    locale: str | None = None
    expires_at: datetime
    accepted_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime


class Integration(BaseModel):
    """A connected external source (provider-agnostic: slack, notion, an MCP
    server, …). credentials_enc is intentionally excluded from the public model."""

    id: UUID
    org_id: UUID
    scope_type: str  # user | team | workspace
    scope_id: UUID
    target_workspace_id: UUID | None = None
    provider: str
    display_name: str | None = None
    status: str = "disconnected"  # connected | error | disconnected | syncing
    config: dict = {}
    last_error: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


class Document(BaseModel):
    id: UUID
    workspace_id: UUID
    filename: str
    file_size: int
    status: DocumentStatus
    qdrant_collection_name: str
    # Embedding profile the document is (being) indexed with (0026); NULL for
    # rows older than fingerprints outside the legacy collection.
    embedding_fingerprint: str | None = None
    object_key: str | None = None
    error_message: str | None = None  # English sentence (API/backcompat)
    # Stable failure code + params (0029, contracts/document_errors.md): the web
    # renders the reason per language; NULL for rows that failed before 0029.
    error_code: str | None = None
    error_params: dict | None = None
    folder_id: UUID | None = None  # Drive folder; NULL = workspace root (0017)
    archived_at: datetime | None = None  # set on ARCHIVE (0017)
    deleted_at: datetime | None = None  # set on soft-DELETE (0017)
    created_at: datetime
    updated_at: datetime


class DocumentFolder(BaseModel):
    """A node in a workspace's document Drive tree (0017). Self-referential:
    parent_folder_id NULL = a root folder. Names are unique per (workspace,
    parent), case-insensitive."""

    id: UUID
    workspace_id: UUID
    parent_folder_id: UUID | None = None
    name: str
    created_at: datetime
    updated_at: datetime
