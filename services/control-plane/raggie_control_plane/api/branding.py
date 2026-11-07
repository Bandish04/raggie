# SPDX-License-Identifier: Apache-2.0

"""White-label branding (platform-wide).

A PUBLIC GET /api/v1/branding serves the product name, tagline, accent color, and
logo/icon as data URLs (so the login page — pre-auth — is branded too). The
platform admin updates text/color via PUT and uploads logo/icon files (stored in
MinIO). Only raster formats identified by their magic bytes are accepted: an SVG
is a scriptable document (stored XSS wherever it is rendered same-origin).
"""

from __future__ import annotations

import base64

import asyncpg
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from raggie_control_plane.api.deps import (
    ensure_platform_admin,
    get_conn,
    get_current_user,
    get_object_store,
)
from raggie_control_plane.db.repositories import SettingsRepo
from raggie_control_plane.infra.objectstore import ObjectStore
from raggie_control_plane.models import User

router = APIRouter(prefix="/api/v1", tags=["branding"])

_MAX_IMAGE_BYTES = 512 * 1024  # 512KB cap (kept small: served inline as a data URL)
_LOGO_KEY = "branding/logo"
_ICON_KEY = "branding/icon"

# Accepted image types, keyed by signature. The client-declared Content-Type is
# never trusted; the stored/served type is the sniffed one.
_ALLOWED_TYPES = ("image/png", "image/jpeg", "image/webp", "image/x-icon")


def _sniff_image(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"\x00\x00\x01\x00"):
        return "image/x-icon"
    return None


class BrandingOut(BaseModel):
    name: str
    tagline: str | None = None
    color: str
    logo_data_url: str | None = None
    icon_data_url: str | None = None


class BrandingUpdate(BaseModel):
    name: str | None = None
    tagline: str | None = None
    color: str | None = None


async def _data_url(store: ObjectStore, key: str | None, content_type: str | None) -> str | None:
    # Anything uploaded before type sniffing (e.g. an SVG) is never served.
    if not key or (content_type or "image/png") not in _ALLOWED_TYPES:
        return None
    try:
        data = await store.get(key)
    except Exception:  # noqa: BLE001 — missing object → no image, never error
        return None
    b64 = base64.b64encode(data).decode()
    return f"data:{content_type or 'image/png'};base64,{b64}"


async def _branding_out(conn: asyncpg.Connection, store: ObjectStore) -> BrandingOut:
    b = await SettingsRepo(conn).get_branding()
    return BrandingOut(
        name=b.get("brand_name") or "Raggie",
        tagline=b.get("brand_tagline"),
        color=b.get("brand_color") or "#0a5bff",
        logo_data_url=await _data_url(store, b.get("brand_logo_key"), b.get("brand_logo_type")),
        icon_data_url=await _data_url(store, b.get("brand_icon_key"), b.get("brand_icon_type")),
    )


@router.get("/branding", response_model=BrandingOut)
async def get_branding(
    conn: asyncpg.Connection = Depends(get_conn),
    store: ObjectStore = Depends(get_object_store),
) -> BrandingOut:
    """Public — the login page and root layout read this before auth."""
    return await _branding_out(conn, store)


@router.put("/admin/branding", response_model=BrandingOut)
async def update_branding(
    body: BrandingUpdate,
    user: User = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
    store: ObjectStore = Depends(get_object_store),
) -> BrandingOut:
    ensure_platform_admin(user)
    fields: dict[str, object] = {}
    if body.name is not None:
        fields["brand_name"] = body.name.strip() or "Raggie"
    if body.tagline is not None:
        fields["brand_tagline"] = body.tagline.strip() or None
    if body.color is not None:
        fields["brand_color"] = body.color.strip() or "#0a5bff"
    await SettingsRepo(conn).update_branding(**fields)
    return await _branding_out(conn, store)


async def _upload_image(
    kind: str, file: UploadFile, user: User, conn: asyncpg.Connection, store: ObjectStore
) -> BrandingOut:
    ensure_platform_admin(user)
    data = await file.read(_MAX_IMAGE_BYTES + 1)  # never buffer more than the cap
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty file")
    if len(data) > _MAX_IMAGE_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "image too large (max 512KB)")
    content_type = _sniff_image(data)
    if content_type is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "file must be a PNG, JPEG, WebP or ICO image"
        )
    key = _LOGO_KEY if kind == "logo" else _ICON_KEY
    await store.put(key, data, content_type)
    await SettingsRepo(conn).update_branding(
        **{f"brand_{kind}_key": key, f"brand_{kind}_type": content_type}
    )
    return await _branding_out(conn, store)


@router.post("/admin/branding/logo", response_model=BrandingOut)
async def upload_logo(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
    store: ObjectStore = Depends(get_object_store),
) -> BrandingOut:
    return await _upload_image("logo", file, user, conn, store)


@router.post("/admin/branding/icon", response_model=BrandingOut)
async def upload_icon(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
    store: ObjectStore = Depends(get_object_store),
) -> BrandingOut:
    return await _upload_image("icon", file, user, conn, store)
