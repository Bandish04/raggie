# SPDX-License-Identifier: Apache-2.0

"""Object store port for raw uploads: in-memory (tests) + MinIO (real)."""

from __future__ import annotations

import asyncio
import io
from typing import Protocol, runtime_checkable


@runtime_checkable
class ObjectStore(Protocol):
    async def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def download_to_file(self, key: str, path: str) -> None: ...

    async def remove(self, key: str) -> None: ...


class InMemoryObjectStore:
    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    async def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        self._store[key] = data

    async def get(self, key: str) -> bytes:
        return self._store[key]

    async def download_to_file(self, key: str, path: str) -> None:
        data = self._store[key]  # KeyError on a missing object → marked FAILED
        with open(path, "wb") as fh:
            fh.write(data)

    async def remove(self, key: str) -> None:
        # Idempotent: removing an absent object is a no-op.
        self._store.pop(key, None)


class MinioObjectStore:
    """S3-compatible object store. The minio SDK is synchronous, so calls run in
    a worker thread to stay non-blocking."""

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
            self._client.put_object,
            self._bucket,
            key,
            io.BytesIO(data),
            len(data),
            content_type,
        )

    async def get(self, key: str) -> bytes:
        resp = await asyncio.to_thread(self._client.get_object, self._bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def _download_to_file_sync(self, key: str, path: str) -> None:
        resp = self._client.get_object(self._bucket, key)
        try:
            with open(path, "wb") as fh:
                for chunk in resp.stream(1024 * 1024):
                    fh.write(chunk)
        finally:
            resp.close()
            resp.release_conn()

    async def download_to_file(self, key: str, path: str) -> None:
        """Stream a (possibly multi-GB) object to disk, never holding it in RAM."""
        await asyncio.to_thread(self._download_to_file_sync, key, path)

    async def remove(self, key: str) -> None:
        """Hard-delete the object. Idempotent: MinIO's remove_object does not
        error when the key is already absent, so re-delivery is safe."""
        await asyncio.to_thread(self._client.remove_object, self._bucket, key)
