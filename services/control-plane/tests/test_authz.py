# SPDX-License-Identifier: Apache-2.0

from raggie_control_plane.authz import Action, Authorizer
from raggie_control_plane.db.repositories import (
    MembershipRepo,
    OrganizationRepo,
    TeamRepo,
    UserRepo,
    WorkspaceRepo,
)


async def _fixture(conn):
    org = await OrganizationRepo(conn).create("Acme")
    eng = await TeamRepo(conn).create(org.id, "Engineering")
    backend = await TeamRepo(conn).create(org.id, "Backend", parent_team_id=eng.id)
    ws = await WorkspaceRepo(conn).create(org.id, "Backend Docs", "INTERNAL", team_id=backend.id)
    return org, eng, backend, ws


async def test_platform_admin_can_do_anything(conn):
    org, _eng, _backend, ws = await _fixture(conn)
    su = await UserRepo(conn).create("su@acme.example", "h", "SUPER_ADMIN", is_platform_admin=True)
    az = Authorizer(conn)
    assert await az.resolve(su, Action.MANAGE_SYSTEM)
    assert await az.resolve(su, Action.MANAGE_ORG, org_id=org.id)
    assert await az.resolve(su, Action.MANAGE_WORKSPACE, workspace_id=ws.id)


async def test_workspace_admin_inherits_manage_from_ancestor_team(conn):
    org, eng, _backend, ws = await _fixture(conn)
    wa = await UserRepo(conn).create("wa@acme.example", "h", "WORKSPACE_ADMIN", org_id=org.id)
    await MembershipRepo(conn).add_team_member(eng.id, wa.id, "WORKSPACE_ADMIN")
    az = Authorizer(conn)
    assert await az.resolve(wa, Action.MANAGE_ORG, org_id=org.id)
    assert await az.resolve(wa, Action.MANAGE_WORKSPACE, workspace_id=ws.id)
    assert not await az.resolve(wa, Action.MANAGE_SYSTEM)


async def test_staff_can_use_but_not_manage(conn):
    org, _eng, _backend, ws = await _fixture(conn)
    staff = await UserRepo(conn).create("st@acme.example", "h", "STAFF", org_id=org.id)
    await MembershipRepo(conn).add_workspace_member(ws.id, staff.id, "STAFF")
    az = Authorizer(conn)
    assert await az.resolve(staff, Action.USE_WORKSPACE_CHAT, workspace_id=ws.id)
    assert await az.resolve(staff, Action.VIEW_WORKSPACE, workspace_id=ws.id)
    assert not await az.resolve(staff, Action.MANAGE_WORKSPACE, workspace_id=ws.id)
    assert not await az.resolve(staff, Action.MANAGE_ORG, org_id=org.id)


async def test_no_access_to_unrelated_workspace(conn):
    _org2 = await OrganizationRepo(conn).create("Other")
    org, _eng, _backend, ws = await _fixture(conn)
    outsider = await UserRepo(conn).create(
        "out@acme.example", "h", "WORKSPACE_ADMIN", org_id=org.id
    )
    az = Authorizer(conn)
    # No membership anywhere -> cannot view or manage the workspace.
    assert not await az.resolve(outsider, Action.VIEW_WORKSPACE, workspace_id=ws.id)
    assert not await az.resolve(outsider, Action.MANAGE_WORKSPACE, workspace_id=ws.id)
