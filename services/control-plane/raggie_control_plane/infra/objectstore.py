# SPDX-License-Identifier: Apache-2.0

"""Object store for raw uploads (control-plane producer side).

Mirrors the workers' ObjectStore contract. The two copies are kept separate
because each service builds from its own Docker context; a shared package would
need a repo-root build context.
"""

from __future__ import annotations

import asyncio
import io
from typing import Protocol, runtime_checkable
from uuid import uuid4


@runtime_checkable
class ObjectStore(Protocol):
    async def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def remove(self, key: str) -> None: ...

    # Resumable multipart upload (large files streamed part-by-part).
    async def create_multipart(self, key: str, content_type: str) -> str: ...

    async def upload_part(self, key: str, upload_id: str, part_number: int, body: bytes) -> str: ...

    async def complete_multipart(
        self, key: str, upload_id: str, parts: list[tuple[int, str]]
    ) -> int: ...

    async def abort_multipart(self, key: str, upload_id: str) -> None: ...


class InMemoryObjectStore:
    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}
        self._parts: dict[tuple[str, str], dict[int, bytes]] = {}

    async def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        self._store[key] = data

    async def get(self, key: str) -> bytes:
        return self._store[key]

    async def remove(self, key: str) -> None:
        self._store.pop(key, None)

    async def create_multipart(self, key: str, content_type: str) -> str:
        upload_id = uuid4().hex
        self._parts[(key, upload_id)] = {}
        return upload_id

    async def upload_part(self, key: str, upload_id: str, part_number: int, body: bytes) -> str:
        self._parts.setdefault((key, upload_id), {})[part_number] = body
        return f'"{part_number}"'

    async def complete_multipart(
        self, key: str, upload_id: str, parts: list[tuple[int, str]]
    ) -> int:
        chunks = self._parts.get((key, upload_id), {})
        data = b"".join(chunks[n] for n, _ in sorted(parts, key=lambda p: p[0]))
        self._store[key] = data
        self._parts.pop((key, upload_id), None)
        return len(data)

    async def abort_multipart(self, key: str, upload_id: str) -> None:
        self._parts.pop((key, upload_id), None)


class MinioObjectStore:
    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
    ) -> None:
        from minio import Minio

        self._client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        self._bucket = bucket

    def _ensure_bucket_sync(self) -> None:
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)

    async def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        await asyncio.to_thread(self._ensure_bucket_sync)
        await asyncio.to_thread(
            self._client.put_object, self._bucket, key, io.BytesIO(data), len(data), content_type
        )

    async def get(self, key: str) -> bytes:
        resp = await asyncio.to_thread(self._client.get_object, self._bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    async def remove(self, key: str) -> None:
        await asyncio.to_thread(self._client.remove_object, self._bucket, key)

    # ── Multipart upload via MinIO compose ────────────────────────────────────
    # The minio SDK has no public per-part API, so each part is stored as its own
    # temp object and the final object is assembled server-side with
    # compose_object (≤10 000 sources, each ≥5 MiB except the last). Stateless for
    # the API: the client holds the upload_id; temp parts live under a key prefix.

    def _part_key(self, key: str, upload_id: str, part_number: int) -> str:
        return f"{key}.mpu/{upload_id}/{part_number:05d}.part"

    def _create_multipart_sync(self, key: str, content_type: str) -> str:
        self._ensure_bucket_sync()
        return uuid4().hex

    async def create_multipart(self, key: str, content_type: str) -> str:
        return await asyncio.to_thread(self._create_multipart_sync, key, content_type)

    def _upload_part_sync(self, key: str, upload_id: str, part_number: int, body: bytes) -> str:
        result = self._client.put_object(
            self._bucket,
            self._part_key(key, upload_id, part_number),
            io.BytesIO(body),
            len(body),
            "application/octet-stream",
        )
        return result.etag or ""

    async def upload_part(self, key: str, upload_id: str, part_number: int, body: bytes) -> str:
        return await asyncio.to_thread(self._upload_part_sync, key, upload_id, part_number, body)

    def _complete_multipart_sync(
        self, key: str, upload_id: str, parts: list[tuple[int, str]]
    ) -> int:
        from minio.commonconfig import ComposeSource

        ordered = sorted(parts, key=lambda p: p[0])
        sources = [
            ComposeSource(self._bucket, self._part_key(key, upload_id, n)) for n, _etag in ordered
        ]
        self._client.compose_object(self._bucket, key, sources)
        for n, _etag in ordered:  # best-effort cleanup of temp parts
            try:
                self._client.remove_object(self._bucket, self._part_key(key, upload_id, n))
            except Exception:  # noqa: BLE001
                pass
        stat = self._client.stat_object(self._bucket, key)
        return int(stat.size or 0)

    async def complete_multipart(
        self, key: str, upload_id: str, parts: list[tuple[int, str]]
    ) -> int:
        """Assemble the uploaded parts into the final object; returns its size."""
        return await asyncio.to_thread(self._complete_multipart_sync, key, upload_id, parts)

    def _abort_multipart_sync(self, key: str, upload_id: str) -> None:
        prefix = f"{key}.mpu/{upload_id}/"
        try:
            for obj in self._client.list_objects(self._bucket, prefix=prefix, recursive=True):
                self._client.remove_object(self._bucket, obj.object_name)
        except Exception:  # noqa: BLE001 — abort is best-effort
            pass

    async def abort_multipart(self, key: str, upload_id: str) -> None:
        await asyncio.to_thread(self._abort_multipart_sync, key, upload_id)
