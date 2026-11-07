# SPDX-License-Identifier: Apache-2.0

"""Admin Qdrant visualization: a 2D PCA projection of stored chunk vectors.

Read-only. Scrolls dense vectors (+ workspace/filename/document payload) from the
collection of the embeddings gateway's active profile, projects them to 2D with
PCA (numpy SVD), and returns the points plus per-document edges so the map
branches into per-file clusters. A SUPER_ADMIN sees their own org (only a
platform admin without an org sees every org); a WORKSPACE_ADMIN sees only
their effective workspaces.
"""

from __future__ import annotations

import asyncpg
import httpx
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from raggie_control_plane.api.deps import get_conn, get_current_user, get_embeddings_profile
from raggie_control_plane.authz import visible_workspaces
from raggie_control_plane.config import settings
from raggie_control_plane.embeddings_profile import EmbeddingsProfile
from raggie_control_plane.models import User

router = APIRouter(prefix="/api/v1/admin", tags=["qdrant-viz"])

# Cap edges per document so a single huge file can't blow up the payload. A star
# topology already yields only n-1 edges per document; this bounds pathological
# cases (one document with thousands of chunks) to a fixed fan-out.
_MAX_EDGES_PER_DOC = 80


def qdrant_headers() -> dict[str, str]:
    """Qdrant API-key auth (QDRANT_API_KEY); no header when unset (dev)."""
    return {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}


class ScatterPoint(BaseModel):
    x: float
    y: float
    workspace_id: str | None = None
    filename: str | None = None
    document_id: str | None = None


class ScatterOut(BaseModel):
    collection: str
    total: int
    points: list[ScatterPoint]
    edges: list[tuple[int, int]] = []


def _document_edges(doc_keys: list[str | None]) -> list[tuple[int, int]]:
    """Star topology per document: the first chunk of each document is the hub
    and links to its siblings. Cheap (single pass, grouped in Python) and bounded
    by _MAX_EDGES_PER_DOC so large files stay calm. Points without a document key
    are left unconnected.
    """
    hubs: dict[str, int] = {}
    counts: dict[str, int] = {}
    edges: list[tuple[int, int]] = []
    for i, key in enumerate(doc_keys):
        if not key:
            continue
        hub = hubs.get(key)
        if hub is None:
            hubs[key] = i
            counts[key] = 0
            continue
        if counts[key] >= _MAX_EDGES_PER_DOC:
            continue
        counts[key] += 1
        edges.append((hub, i))
    return edges


@router.get("/qdrant/scatter", response_model=ScatterOut)
async def qdrant_scatter(
    limit: int = Query(default=1500, ge=1, le=4000),
    user: User = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
    profile: EmbeddingsProfile = Depends(get_embeddings_profile),
) -> ScatterOut:
    if user.role not in ("SUPER_ADMIN", "WORKSPACE_ADMIN"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")

    coll = profile.active_collection
    if coll is None:  # gateway not reached yet: nothing to name, nothing to show
        return ScatterOut(collection="", total=0, points=[], edges=[])

    # The collection is shared by every org. Qdrant itself filters every scroll
    # to the caller's visible workspaces (an org-less platform admin's set is
    # every workspace), so other tenants' points are never loaded; the check
    # on each returned point below is defense in depth. No visible workspace:
    # no request at all (an empty "any" would not be a filter).
    allowed = {str(w.id) for w in await visible_workspaces(conn, user)}
    if not allowed:
        return ScatterOut(collection=coll, total=0, points=[], edges=[])
    workspace_filter = {"must": [{"key": "workspace_id", "match": {"any": sorted(allowed)}}]}

    vectors: list[list[float]] = []
    # (workspace_id, filename, document_id) — document_id is the grouping key
    # used both for edges and for per-document coloring on the client.
    meta: list[tuple[str | None, str | None, str | None]] = []
    offset = None
    try:
        async with httpx.AsyncClient(timeout=20, headers=qdrant_headers()) as client:
            while len(vectors) < limit:
                body: dict = {
                    "filter": workspace_filter,
                    "limit": min(512, limit - len(vectors)),
                    "with_vector": ["dense"],
                    "with_payload": ["workspace_id", "filename", "document_id"],
                }
                if offset is not None:
                    body["offset"] = offset
                resp = await client.post(
                    f"{settings.qdrant_url}/collections/{coll}/points/scroll", json=body
                )
                if resp.status_code != 200:
                    break
                result = resp.json().get("result", {})
                pts = result.get("points", [])
                for p in pts:
                    payload = p.get("payload") or {}
                    ws = payload.get("workspace_id")
                    if ws not in allowed:
                        continue
                    vec = p.get("vector")
                    dense = vec.get("dense") if isinstance(vec, dict) else vec
                    if dense:
                        vectors.append(dense)
                        filename = payload.get("filename")
                        # Prefer an explicit document_id; fall back to filename so
                        # chunks of the same file still group into one cluster.
                        doc_id = payload.get("document_id")
                        if doc_id is not None:
                            doc_id = str(doc_id)
                        elif filename is not None:
                            doc_id = str(filename)
                        meta.append((ws, filename, doc_id))
                offset = result.get("next_page_offset")
                if offset is None or not pts:
                    break
    except httpx.HTTPError:
        return ScatterOut(collection=coll, total=0, points=[], edges=[])

    doc_keys = [m[2] for m in meta]
    edges = _document_edges(doc_keys)

    if len(vectors) < 2:
        pts_out = [
            ScatterPoint(x=0.0, y=0.0, workspace_id=m[0], filename=m[1], document_id=m[2])
            for m in meta
        ]
        return ScatterOut(collection=coll, total=len(pts_out), points=pts_out, edges=edges)

    # PCA scores via thin SVD: coords = U[:, :2] * S[:2].
    X = np.asarray(vectors, dtype=float)
    X = X - X.mean(axis=0)
    u, s, _ = np.linalg.svd(X, full_matrices=False)
    coords = u[:, :2] * s[:2]
    points = [
        ScatterPoint(
            x=float(coords[i, 0]),
            y=float(coords[i, 1]),
            workspace_id=meta[i][0],
            filename=meta[i][1],
            document_id=meta[i][2],
        )
        for i in range(len(vectors))
    ]
    return ScatterOut(collection=coll, total=len(points), points=points, edges=edges)
