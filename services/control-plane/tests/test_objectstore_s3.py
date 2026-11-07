# SPDX-License-Identifier: Apache-2.0

"""MinioObjectStore against a real S3-compatible server (SeaweedFS, MinIO, ...).

Skipped unless OBJECTSTORE_TEST_ENDPOINT (host:port) is set, together with
OBJECTSTORE_TEST_ACCESS_KEY / OBJECTSTORE_TEST_SECRET_KEY. Each test uses a fresh
bucket, so the store's create-on-first-write path is exercised too.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from minio.error import S3Error

from raggie_control_plane.infra.objectstore import MinioObjectStore

ENDPOINT = os.environ.get("OBJECTSTORE_TEST_ENDPOINT", "")

# Opt-in suite: skipped unless OBJECTSTORE_TEST_ENDPOINT is set (CI included);
# configured but unreachable fails under CI=true (see tests/_infra.py).
pytestmark = pytest.mark.requires_s3

MIB = 1024 * 1024


@pytest.fixture
def store():
    s = MinioObjectStore(
        endpoint=ENDPOINT,
        access_key=os.environ.get("OBJECTSTORE_TEST_ACCESS_KEY", ""),
        secret_key=os.environ.get("OBJECTSTORE_TEST_SECRET_KEY", ""),
        bucket=f"raggie-test-{uuid4().hex[:12]}",
    )
    yield s
    client = s._client
    if client.bucket_exists(s._bucket):
        for obj in client.list_objects(s._bucket, recursive=True):
            client.remove_object(s._bucket, obj.object_name)
        client.remove_bucket(s._bucket)


def _keys(store: MinioObjectStore, prefix: str = "") -> list[str]:
    return [
        o.object_name
        for o in store._client.list_objects(store._bucket, prefix=prefix, recursive=True)
    ]


async def test_put_get_remove_roundtrip(store) -> None:
    key = "org/ws/doc.pdf"
    await store.put(key, b"%PDF-1.7 hello", "application/pdf")
    assert await store.get(key) == b"%PDF-1.7 hello"
    stat = store._client.stat_object(store._bucket, key)
    assert stat.content_type == "application/pdf"

    await store.remove(key)
    assert _keys(store) == []
    with pytest.raises(S3Error, match="NoSuchKey"):
        await store.get(key)
    # Re-delivered deletes must not fail.
    await store.remove(key)


async def test_multipart_upload_assembles_parts_in_order(store) -> None:
    key = "org/ws/big.bin"
    part1 = os.urandom(5 * MIB)  # every part but the last must be >= 5 MiB
    part2 = os.urandom(5 * MIB + 17)
    part3 = b"tail"
    upload_id = await store.create_multipart(key, "application/octet-stream")
    # Parts may arrive out of order; completion orders them by number.
    etag3 = await store.upload_part(key, upload_id, 3, part3)
    etag1 = await store.upload_part(key, upload_id, 1, part1)
    etag2 = await store.upload_part(key, upload_id, 2, part2)
    assert all([etag1, etag2, etag3])

    size = await store.complete_multipart(key, upload_id, [(2, etag2), (3, etag3), (1, etag1)])

    assert size == len(part1) + len(part2) + len(part3)
    assert await store.get(key) == part1 + part2 + part3
    assert _keys(store) == [key]  # temp part objects are cleaned up


async def test_abort_multipart_removes_uploaded_parts(store) -> None:
    key = "org/ws/abandoned.bin"
    upload_id = await store.create_multipart(key, "application/octet-stream")
    await store.upload_part(key, upload_id, 1, os.urandom(5 * MIB))
    await store.upload_part(key, upload_id, 2, b"rest")
    assert len(_keys(store, f"{key}.mpu/{upload_id}/")) == 2

    await store.abort_multipart(key, upload_id)

    assert _keys(store) == []
