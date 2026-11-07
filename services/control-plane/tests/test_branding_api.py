# SPDX-License-Identifier: Apache-2.0

"""Brand logo/icon uploads: raster formats only, sniffed from magic bytes."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from httpx import ASGITransport

from raggie_control_plane.api.deps import get_conn, get_current_user, get_object_store
from raggie_control_plane.db.repositories import OrganizationRepo, SettingsRepo, UserRepo
from raggie_control_plane.infra.objectstore import InMemoryObjectStore
from raggie_control_plane.main import app

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 64
ICO = b"\x00\x00\x01\x00\x01\x00" + b"\x00" * 64
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(document.cookie)</script></svg>'


@asynccontextmanager
async def _platform_admin_client(conn) -> AsyncIterator[tuple[httpx.AsyncClient, object]]:
    org = await OrganizationRepo(conn).create("Brand")
    pa = await UserRepo(conn).create(
        "pa@brand.test", "h", "SUPER_ADMIN", org_id=org.id, is_platform_admin=True
    )
    store = InMemoryObjectStore()

    async def _conn_override():
        yield conn

    app.dependency_overrides[get_conn] = _conn_override
    app.dependency_overrides[get_current_user] = lambda: pa
    app.dependency_overrides[get_object_store] = lambda: store
    try:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, store
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("data", "expected_type"),
    [(PNG, "image/png"), (JPEG, "image/jpeg"), (WEBP, "image/webp"), (ICO, "image/x-icon")],
)
async def test_raster_icons_accepted_with_sniffed_type(conn, data, expected_type) -> None:
    async with _platform_admin_client(conn) as (client, _store):
        # The client-declared type is ignored; the stored type comes from the bytes.
        r = await client.post(
            "/api/v1/admin/branding/icon", files={"file": ("x.bin", data, "image/svg+xml")}
        )
        assert r.status_code == 200
        assert r.json()["icon_data_url"].startswith(f"data:{expected_type};base64,")


@pytest.mark.parametrize("kind", ["icon", "logo"])
async def test_svg_upload_rejected(conn, kind) -> None:
    async with _platform_admin_client(conn) as (client, store):
        r = await client.post(
            f"/api/v1/admin/branding/{kind}", files={"file": ("x.png", SVG, "image/png")}
        )
        assert r.status_code == 400
        r = await client.post(
            f"/api/v1/admin/branding/{kind}", files={"file": ("x.svg", SVG, "image/svg+xml")}
        )
        assert r.status_code == 400


async def test_oversized_icon_rejected(conn) -> None:
    async with _platform_admin_client(conn) as (client, _store):
        big = PNG + b"\x00" * (512 * 1024)
        r = await client.post(
            "/api/v1/admin/branding/icon", files={"file": ("x.png", big, "image/png")}
        )
        assert r.status_code == 413


async def test_previously_stored_svg_is_not_served(conn) -> None:
    async with _platform_admin_client(conn) as (client, store):
        await store.put("branding/icon", SVG, "image/svg+xml")
        await SettingsRepo(conn).update_branding(
            brand_icon_key="branding/icon", brand_icon_type="image/svg+xml"
        )
        r = await client.get("/api/v1/branding")
        assert r.status_code == 200 and r.json()["icon_data_url"] is None
