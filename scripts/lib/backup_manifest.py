#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""manifest.json for scripts/backup.sh and scripts/restore.sh (stdlib only).

    backup_manifest.py hash-objects DIR          write DIR/objects.sha256
    backup_manifest.py write DIR [--str|--num|--json KEY=VALUE]...
    backup_manifest.py verify DIR                check the backup against its manifest (exit 1)
    backup_manifest.py collections DIR           print the (validated) collections to restore
    backup_manifest.py get DIR KEY               print a dotted key ("" when absent)

Artifacts are every file in the backup except manifest.json and objects/**, whose
files are listed with their sha256 in objects.sha256 (itself an artifact), so a
backup with many uploads keeps a small manifest.

verify is scoped to the manifest: what a restore uses (postgres.dump, every
snapshot in "qdrant", objects.sha256 for local objects) must be listed, every
listed file must match its sha256, and any other file or a symlink anywhere in
the backup fails it. With BACKUP_MANIFEST_KEY set, write also stores an
HMAC-SHA256 of manifest.json in manifest.json.hmac and verify requires it to
match (without the key, a signature present is reported but not checked).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath

FORMAT = 1
OBJECTS = "objects"
OBJECTS_SUMS = "objects.sha256"
MANIFEST = "manifest.json"
SIGNATURE = "manifest.json.hmac"
KEY_ENV = "BACKUP_MANIFEST_KEY"
COLLECTION = re.compile(r"^[A-Za-z0-9_-]+$")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def hash_objects(root: Path) -> None:
    objects = root / OBJECTS
    lines = [
        f"{sha256(p)}  {p.relative_to(objects).as_posix()}"
        for p in (_files(objects) if objects.is_dir() else [])
    ]
    (root / OBJECTS_SUMS).write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def _set(doc: dict, dotted: str, value: object) -> None:
    *parents, leaf = dotted.split(".")
    for key in parents:
        doc = doc.setdefault(key, {})
    doc[leaf] = value


def write(root: Path, args: list[str]) -> None:
    doc: dict = {"format": FORMAT}
    it = iter(args)
    for flag in it:
        key, _, raw = next(it).partition("=")
        if flag == "--str":
            _set(doc, key, raw)
        elif flag == "--num":
            _set(doc, key, int(raw or 0))
        elif flag == "--json":
            _set(doc, key, json.loads(raw))
        else:
            raise SystemExit(f"unknown option {flag}")
    doc["artifacts"] = [
        {"path": p.relative_to(root).as_posix(), "bytes": p.stat().st_size, "sha256": sha256(p)}
        for p in _files(root)
        if p.relative_to(root).as_posix() not in (MANIFEST, SIGNATURE)
        and p.relative_to(root).parts[0] != OBJECTS
    ]
    out = root / MANIFEST
    out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(out, 0o600)
    key = os.environ.get(KEY_ENV, "")
    if key:
        sig = root / SIGNATURE
        sig.write_text(_hmac(key, out) + "\n", encoding="utf-8")
        os.chmod(sig, 0o600)


def _hmac(key: str, path: Path) -> str:
    return hmac.new(key.encode("utf-8"), path.read_bytes(), hashlib.sha256).hexdigest()


def _safe_rel(rel: str) -> bool:
    p = PurePosixPath(rel)
    return bool(rel) and not p.is_absolute() and ".." not in p.parts


def _snapshots(doc: dict) -> tuple[list[tuple[str, str]], list[str]]:
    """(collection, file) pairs from doc["qdrant"], and the problems found."""
    out: list[tuple[str, str]] = []
    problems: list[str] = []
    for q in doc.get("qdrant") or []:
        name = str(q.get("collection", ""))
        if not COLLECTION.match(name):
            problems.append(f"collection name not allowed: {name!r}")
            continue
        file = f"qdrant/{name}.snapshot"
        if q.get("file") != file:
            problems.append(f"snapshot of {name} must be {file}, not {q.get('file')!r}")
            continue
        out.append((name, file))
    return out, problems


def _walk(root: Path) -> tuple[set[str], list[str]]:
    """Every file under root (relative posix paths) and every symlink found."""
    files: set[str] = set()
    links: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                links.append(rel)
            elif name in filenames:
                files.add(rel)
        dirnames[:] = [d for d in dirnames if not (Path(dirpath) / d).is_symlink()]
    return files, sorted(links)


def _signature(root: Path) -> list[str]:
    key = os.environ.get(KEY_ENV, "")
    sig = root / SIGNATURE
    if not key:
        if sig.is_file():
            print(f"{SIGNATURE} present but {KEY_ENV} is not set: not checked", file=sys.stderr)
        return []
    if not sig.is_file():
        return [f"{MANIFEST} is not signed ({KEY_ENV} is set but there is no {SIGNATURE})"]
    want = _hmac(key, root / MANIFEST)
    if not hmac.compare_digest(sig.read_text(encoding="utf-8").strip(), want):
        return [f"{MANIFEST} HMAC mismatch (wrong {KEY_ENV}, or the manifest was changed)"]
    return []


def verify(root: Path) -> int:
    manifest = root / MANIFEST
    if not manifest.is_file() or manifest.is_symlink():
        print(f"no {MANIFEST} in {root}", file=sys.stderr)
        return 1
    problems = _signature(root)
    if problems:
        print(problems[0], file=sys.stderr)
        return 1
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    if doc.get("format") != FORMAT:
        print(f"unsupported manifest format {doc.get('format')!r}", file=sys.stderr)
        return 1
    present, links = _walk(root)
    problems += [f"symlink: {rel}" for rel in links]

    listed: dict[str, str] = {}
    for art in doc.get("artifacts", []):
        rel = str(art.get("path", ""))
        if not _safe_rel(rel) or rel.split("/", 1)[0] == OBJECTS or rel in (MANIFEST, SIGNATURE):
            problems.append(f"artifact path not allowed: {rel!r}")
            continue
        listed[rel] = str(art.get("sha256", ""))

    snapshots, bad = _snapshots(doc)
    problems += bad
    required = ["postgres.dump", *(file for _c, file in snapshots)]
    if (doc.get("objects") or {}).get("location") == OBJECTS:
        required.append(OBJECTS_SUMS)
    problems += [f"not listed: {rel}" for rel in required if rel not in listed]

    for rel, digest in listed.items():
        path = root / rel
        if rel not in present:
            problems.append(f"missing: {rel}")
        elif sha256(path) != digest:
            problems.append(f"sha256 mismatch: {rel}")

    allowed = {MANIFEST, SIGNATURE, *listed}
    if OBJECTS_SUMS in listed and OBJECTS_SUMS in present:
        for line in (root / OBJECTS_SUMS).read_text(encoding="utf-8").splitlines():
            digest, _, rel = line.partition("  ")
            name = f"{OBJECTS}/{rel}"
            if not _safe_rel(rel):
                problems.append(f"object path not allowed: {rel!r}")
            elif name not in present:
                problems.append(f"missing: {name}")
            elif sha256(root / name) != digest:
                problems.append(f"sha256 mismatch: {name}")
            allowed.add(name)
    problems += [f"unlisted: {rel}" for rel in sorted(present - allowed)]
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


def collections(root: Path) -> int:
    doc = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    snapshots, problems = _snapshots(doc)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    for name, _file in snapshots:
        print(name)
    return 0


def get(root: Path, dotted: str) -> None:
    value: object = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for key in dotted.split("."):
        if isinstance(value, list) and key.isdigit() and int(key) < len(value):
            value = value[int(key)]
        elif isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return
    print(value if isinstance(value, str) else json.dumps(value))


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    cmd, root = argv[0], Path(argv[1])
    if cmd == "hash-objects":
        hash_objects(root)
    elif cmd == "write":
        write(root, argv[2:])
    elif cmd == "verify":
        return verify(root)
    elif cmd == "collections":
        return collections(root)
    elif cmd == "get" and len(argv) == 3:
        get(root, argv[2])
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
