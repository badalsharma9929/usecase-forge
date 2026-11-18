"""Persistence for run snapshots.

Every write creates a new, never-overwritten object (``runs/<id>/<seq>.<rev>.json``),
and readers take the highest name. Immutable writes sidestep any read-after-overwrite
caching, and give a free audit trail of each step.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Protocol


def _snapshot_path(run_id: str, seq: int, rev: int) -> str:
    return f"runs/{run_id}/{seq:04d}.{rev:03d}.json"


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class RunStore(Protocol):
    def save(self, snapshot: dict) -> None: ...
    def latest(self, run_id: str) -> dict | None: ...
    def record_server_run(self, run_id: str) -> None: ...
    def server_runs_today(self) -> int: ...


class MemoryRunStore:
    """For tests and single-process local development."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def save(self, snapshot: dict) -> None:
        path = _snapshot_path(snapshot["id"], snapshot["seq"], snapshot["rev"])
        with self._lock:
            self._objects[path] = json.dumps(snapshot).encode()

    def latest(self, run_id: str) -> dict | None:
        with self._lock:
            names = [p for p in self._objects if p.startswith(f"runs/{run_id}/")]
            return json.loads(self._objects[max(names)]) if names else None

    def record_server_run(self, run_id: str) -> None:
        with self._lock:
            self._objects[f"quota/{today()}/{run_id}"] = b"1"

    def server_runs_today(self) -> int:
        with self._lock:
            return sum(1 for p in self._objects if p.startswith(f"quota/{today()}/"))


class BlobRunStore:
    """Vercel Blob (private store). Needs BLOB_READ_WRITE_TOKEN in the environment."""

    def __init__(self) -> None:
        from vercel.blob import sync

        self._blob = sync

    def save(self, snapshot: dict) -> None:
        path = _snapshot_path(snapshot["id"], snapshot["seq"], snapshot["rev"])
        self._blob.put_blob(
            path,
            json.dumps(snapshot).encode(),
            access="private",
            content_type="application/json",
            allow_overwrite=True,  # a redelivered step may legitimately rewrite its own snapshot
        )

    def latest(self, run_id: str) -> dict | None:
        names = [b.pathname for b in self._blob.query_blobs(prefix=f"runs/{run_id}/")]
        if not names:
            return None
        return json.loads(self._blob.get_blob(max(names), access="private").body)

    def record_server_run(self, run_id: str) -> None:
        self._blob.put_blob(f"quota/{today()}/{run_id}", b"1", access="private", allow_overwrite=True)

    def server_runs_today(self) -> int:
        return sum(1 for _ in self._blob.query_blobs(prefix=f"quota/{today()}/"))
