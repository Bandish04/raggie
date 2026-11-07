# SPDX-License-Identifier: Apache-2.0

"""Repositories — the storage seam (keeps SQL out of the API layer).

Each repository wraps an ``asyncpg.Connection`` and speaks explicit SQL against
the single-source-of-truth schema. Acquiring a connection per request keeps
transactions explicit and is compatible with PgBouncer transaction pooling.

Read/write routing can be layered on top: the connection passed
in may come from a read-replica pool for read-only methods. The methods
themselves do not encode routing.

The repositories live in domain modules; import them from this package
(``from raggie_control_plane.db.repositories import UserRepo``).
"""

from __future__ import annotations

# Kept importable from here for backward compatibility: the single-module
# repositories.py exposed these names through its own imports.
from collections.abc import Iterable  # noqa: F401
from datetime import datetime  # noqa: F401
from uuid import UUID  # noqa: F401

from raggie_control_plane.config import settings  # noqa: F401
from raggie_control_plane.db.repositories._common import compose_sql
from raggie_control_plane.db.repositories.audit_analytics import AnalyticsRepo, AuditRepo
from raggie_control_plane.db.repositories.documents import DocumentFolderRepo, DocumentRepo
from raggie_control_plane.db.repositories.integrations import IntegrationRepo
from raggie_control_plane.db.repositories.orgs_teams import (
    DepartmentRepo,
    LocationRepo,
    MembershipRepo,
    OrganizationRepo,
    TeamRepo,
)
from raggie_control_plane.db.repositories.skills import SkillsRepo
from raggie_control_plane.db.repositories.system_settings import SettingsRepo
from raggie_control_plane.db.repositories.tasks import NotificationRepo, ScheduledTaskRepo
from raggie_control_plane.db.repositories.users import (
    AuthSessionRepo,
    InviteRepo,
    UserIdentityRepo,
    UserMemoryRepo,
    UserRepo,
)
from raggie_control_plane.db.repositories.workspaces import WorkspaceRepo
from raggie_control_plane.models import (  # noqa: F401
    Department,
    Document,
    DocumentFolder,
    Integration,
    Invite,
    Location,
    Notification,
    Organization,
    ScheduledTask,
    Skill,
    SkillVersion,
    Team,
    User,
    Workspace,
)

__all__ = [
    "AnalyticsRepo",
    "AuditRepo",
    "AuthSessionRepo",
    "DepartmentRepo",
    "DocumentFolderRepo",
    "DocumentRepo",
    "IntegrationRepo",
    "InviteRepo",
    "LocationRepo",
    "MembershipRepo",
    "NotificationRepo",
    "OrganizationRepo",
    "ScheduledTaskRepo",
    "SettingsRepo",
    "SkillsRepo",
    "TeamRepo",
    "UserIdentityRepo",
    "UserMemoryRepo",
    "UserRepo",
    "WorkspaceRepo",
    "compose_sql",
]
