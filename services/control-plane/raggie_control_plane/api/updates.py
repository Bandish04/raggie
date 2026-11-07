# SPDX-License-Identifier: Apache-2.0

"""Self-hosted update check (platform admin).

Compares the running version against a remote release manifest and reports whether
an update is available, plus the changelog and the operator command to run. This
NEVER touches the host from the web — by design, a KVKK/on-prem-safe notifier, not
a remote executor.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from raggie_control_plane.api.deps import ensure_platform_admin, get_current_user
from raggie_control_plane.config import settings
from raggie_control_plane.models import User

router = APIRouter(prefix="/api/v1/admin", tags=["updates"])


class UpdateStatus(BaseModel):
    current_version: str
    latest_version: str | None = None
    update_available: bool = False
    notes: str | None = None
    release_url: str | None = None
    update_command: str
    checked: bool = False  # False when no manifest URL is configured / fetch failed


def _https_url(value: object) -> str | None:
    """The manifest is remote data and its url becomes a link in the admin UI:
    keep only an absolute https URL, drop anything else (javascript:, data:,
    http:, relative, non-string)."""
    if not isinstance(value, str):
        return None
    url = value.strip()
    parts = urlsplit(url)
    return url if parts.scheme.lower() == "https" and parts.netloc else None


def _parse_version(v: str) -> tuple[int, ...]:
    """Loose semver tuple; non-numeric suffixes are ignored. '1.2.3' -> (1,2,3)."""
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums[:4]) or (0,)


@router.get("/updates", response_model=UpdateStatus)
async def check_updates(user: User = Depends(get_current_user)) -> UpdateStatus:
    ensure_platform_admin(user)

    current = settings.app_version
    base = UpdateStatus(current_version=current, update_command=settings.update_command)
    if not settings.release_manifest_url:
        return base  # no manifest configured → just report the current version

    try:
        async with httpx.AsyncClient(timeout=6) as client:
            resp = await client.get(settings.release_manifest_url)
        if resp.status_code != 200:
            return base
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return base  # offline / malformed → fail-soft, no error to the admin

    latest = str(data.get("version") or "").strip() or None
    base.latest_version = latest
    base.notes = data.get("notes")
    base.release_url = _https_url(data.get("url"))
    base.checked = True
    if latest:
        base.update_available = _parse_version(latest) > _parse_version(current)
    return base
