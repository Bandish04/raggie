# SPDX-License-Identifier: Apache-2.0

"""db/repositories was split from one module into a package; every name the
old module exposed must still import from `raggie_control_plane.db.repositories`."""

import importlib
from pathlib import Path

import raggie_control_plane.db.repositories as repositories

# Public names of the single-module repositories.py right before the split.
PRE_SPLIT_PUBLIC_NAMES = {
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
    # Names the old module imported and therefore also exposed.
    "Department",
    "Document",
    "DocumentFolder",
    "Integration",
    "Invite",
    "Location",
    "Notification",
    "Organization",
    "ScheduledTask",
    "Skill",
    "SkillVersion",
    "Team",
    "User",
    "Workspace",
    "Iterable",
    "UUID",
    "datetime",
    "settings",
}
REPOSITORY_API = {n for n in PRE_SPLIT_PUBLIC_NAMES if n.endswith("Repo")} | {"compose_sql"}


def test_every_pre_split_name_still_imports() -> None:
    public = {n for n in vars(repositories) if not n.startswith("_")}
    missing = PRE_SPLIT_PUBLIC_NAMES - public
    assert not missing


def test_all_is_the_repository_api() -> None:
    assert set(repositories.__all__) == REPOSITORY_API


def test_repositories_live_in_domain_modules() -> None:
    package_dir = Path(repositories.__file__).parent
    assert repositories.__file__.endswith("__init__.py")
    for name in REPOSITORY_API:
        module = getattr(repositories, name).__module__
        assert module.startswith("raggie_control_plane.db.repositories."), (name, module)
        assert (package_dir / f"{module.rsplit('.', 1)[1]}.py").exists()
        assert getattr(importlib.import_module(module), name) is getattr(repositories, name)
