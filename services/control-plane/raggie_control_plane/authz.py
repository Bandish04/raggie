# SPDX-License-Identifier: Apache-2.0

"""Central authorization policy (RBAC + ABAC over the team tree).

A single decision function — ``Authorizer.resolve`` — is the one place that
answers "can this user perform this action on this resource?". Workspace
access uses the closure-table-backed effective-access resolution, so membership
in an ancestor team grants access to descendant workspaces.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

import asyncpg

from raggie_control_plane.db.repositories import MembershipRepo, WorkspaceRepo
from raggie_control_plane.models import Role, User, Workspace


class Action(StrEnum):
    MANAGE_SYSTEM = "manage_system"  # platform admin only: all orgs, global settings
    MANAGE_ORG = "manage_org"  # create teams/workspaces, invite users within an org
    VIEW_WORKSPACE = "view_workspace"
    USE_WORKSPACE_CHAT = "use_workspace_chat"
    MANAGE_WORKSPACE = "manage_workspace"  # docs / members / settings of a workspace


# Role hierarchy (higher rank = more authority). A user may never grant —
# by invite, creation or role change — a role ranked above their own.
ROLE_RANK: dict[Role, int] = {Role.STAFF: 0, Role.WORKSPACE_ADMIN: 1, Role.SUPER_ADMIN: 2}


def can_grant_role(actor: User, role: Role | str) -> bool:
    return ROLE_RANK[Role(role)] <= ROLE_RANK[Role(actor.role)]


def is_platform_admin(user: User) -> bool:
    return bool(user.is_platform_admin) and user.is_active


async def visible_workspaces(conn: asyncpg.Connection, user: User) -> list[Workspace]:
    """Workspaces an admin listing / analytics view may cover: a SUPER_ADMIN sees
    their own org; only a platform admin without an org sees every org; anyone
    else sees their effective (membership-derived) workspaces."""
    repo = WorkspaceRepo(conn)
    if user.role == Role.SUPER_ADMIN or is_platform_admin(user):
        if user.org_id is not None:
            return await repo.list_by_org(user.org_id)
        return await repo.list_all() if is_platform_admin(user) else []
    ids = await MembershipRepo(conn).effective_workspace_ids(user.id)
    return await repo.list_by_ids(ids)


class Authorizer:
    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn
        self._members = MembershipRepo(conn)

    async def resolve(
        self,
        user: User,
        action: Action,
        *,
        org_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> bool:
        # The platform admin (operator) is authorized for everything, every org.
        if is_platform_admin(user):
            return True
        if action == Action.MANAGE_SYSTEM:
            return False
        # SUPER_ADMIN has full authority — but only inside their own org.
        if user.role == Role.SUPER_ADMIN:
            if user.org_id is None:
                return False
            if action == Action.MANAGE_ORG:
                return org_id is not None and org_id == user.org_id
            if workspace_id is None:
                return False
            ws_org = await self._conn.fetchval(
                "SELECT org_id FROM workspaces WHERE id = $1", workspace_id
            )
            return ws_org is not None and ws_org == user.org_id
        if action == Action.MANAGE_ORG:
            return (
                user.role == Role.WORKSPACE_ADMIN and org_id is not None and user.org_id == org_id
            )
        if action in (
            Action.VIEW_WORKSPACE,
            Action.USE_WORKSPACE_CHAT,
            Action.MANAGE_WORKSPACE,
        ):
            if workspace_id is None:
                return False
            effective = await self._members.effective_workspace_ids(user.id)
            if workspace_id not in effective:
                return False
            if action == Action.MANAGE_WORKSPACE:
                return user.role == Role.WORKSPACE_ADMIN
            return True  # VIEW / USE allowed for any role with access
        return False
