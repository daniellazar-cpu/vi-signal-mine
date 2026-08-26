"""The storage contract: two ``Protocol``s a backend must satisfy (spec D16).

``vsm.topics.store.TopicStore`` and ``vsm.runs.store.RunStore`` are the
SQLite-plus-filesystem implementations that exist today. ``PostgresTopicStore``
/ ``PostgresRunStore`` (``vsm/backends/postgres.py``) and ``BlobTopicStore`` /
``BlobRunStore`` (``vsm/backends/vercel_blob.py``) satisfy the same two
Protocols against, respectively, a real database and Vercel Blob's HTTP API —
``open_stores`` below picks among all three. The constraint they all answer
to: only ``/tmp`` is writable on a Vercel serverless function, and it belongs
to a single invocation, so nothing that must survive a request can go through
a bare local file there.

Declaring the ``Protocol``s costs about forty lines and buys a contract every
backend has to satisfy — checked by the shared, parametrised suite in
``tests/test_storage_contract.py``, not by a resemblance to whatever the
first implementation happened to do. That suite, not this file, is where the
three backends are actually kept from drifting apart.

Deliberately no SQL/HTTP dialect shim: ``TopicStore`` and ``RunStore`` write
their own SQL, the Postgres pair writes its own, and the Blob pair writes its
own HTTP calls. A shim papering over ``?`` vs ``%s`` vs a REST call is where
the subtle bugs live; three clear implementations of a 5-column and a
9-column table are worth the duplication.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

from vsm.backends.dburl import resolve_db_url
from vsm.config import Settings
from vsm.runs.model import Run
from vsm.runs.store import RunStore
from vsm.topics.model import Topic
from vsm.topics.store import TopicStore

__all__ = ["TopicStoreLike", "RunStoreLike", "open_stores"]

_log = logging.getLogger(__name__)


@runtime_checkable
class TopicStoreLike(Protocol):
    """Everything a topic store must do, independent of backend."""

    def create(self, **kwargs: Any) -> Topic: ...

    def get(self, topic_id: str) -> Topic: ...

    def list(self) -> list[Topic]: ...

    def update(self, topic_id: str, **fields: Any) -> Topic: ...


@runtime_checkable
class RunStoreLike(Protocol):
    """Everything a run store must do, independent of backend.

    ``snapshots()`` order is part of the contract, not an implementation
    detail of the SQLite backend: a later delta pass decides which snapshot
    came before another by *position in this list*. Any backend — SQLite
    ``seq`` column, Postgres sequence, or otherwise — must return completed
    MINE runs oldest first by a monotonic counter, and never by comparing
    timestamps, because two runs created in the same microsecond compare
    equal on a clock and would silently drop a baseline.
    """

    def start(
        self, topic_id: str, mode: str, parent_run_id: str | None = None
    ) -> Run: ...

    def finish(
        self, run_id: str, status: str, cost_usd: float, note: str = ""
    ) -> Run: ...

    def get(self, run_id: str) -> Run: ...

    def for_topic(self, topic_id: str, mode: str | None = None) -> list[Run]: ...

    def snapshots(self, topic_id: str) -> list[Run]: ...

    def artifacts_dir(self, run_id: str) -> Path: ...

    #: A backend's artifact key/path must reject a name that escapes its
    #: storage root, the same way the local filesystem store rejects a name
    #: that escapes the run directory — a blob key built by string-joining a
    #: caller-supplied name is exactly as traversable as a filesystem path.
    def write_artifact(self, run_id: str, name: str, payload: Any) -> Path: ...

    def read_artifact(self, run_id: str, name: str) -> Any: ...


def open_stores(
    settings: Settings, env: Mapping[str, str] | None = None
) -> tuple[TopicStoreLike, RunStoreLike]:
    """Postgres when a database URL resolves, then Vercel Blob when
    ``BLOB_READ_WRITE_TOKEN`` is set, then SQLite-plus-filesystem. ``env`` is
    injectable for tests; production callers (``vsm/app.py``) leave it at
    ``None`` and get ``os.environ``.

    Postgres wins over Blob when both are configured: a real database is the
    stronger guarantee (transactions, a real query engine) and this project
    already had it working before Blob was ever provisioned — nothing here
    forces a choice between them, but the ordering has to be *some* fixed
    order, so the more capable backend goes first.

    Deliberately does not import ``vsm.backends.postgres`` / ``.vercel_blob``
    at module scope — the former imports ``psycopg``, an optional extra
    never a core dependency (``httpx``, which the latter uses, already is
    one), and the whole point of both ``resolve_db_url`` and a missing Blob
    token returning nothing is that a plain local install with neither
    configured must still work.

    Logs which backend it picked, at INFO, and names the *consequence*
    rather than the condition — the parent engine's equivalent warning went
    nowhere because nothing had configured a log handler, so the one signal
    saying "your writes are being lost" was silently discarded. Naming the
    consequence means even a bare, unconfigured root logger printing to
    stderr says something an operator would notice.
    """
    env = env if env is not None else os.environ
    db_url = resolve_db_url(env)
    if db_url:
        from vsm.backends.postgres import PostgresRunStore, PostgresTopicStore

        _log.info(
            "storage backend: Postgres (a database URL is configured) — "
            "topics, runs and artifacts survive across invocations"
        )
        return PostgresTopicStore(db_url), PostgresRunStore(db_url)

    blob_token = (env.get("BLOB_READ_WRITE_TOKEN") or "").strip()
    if blob_token:
        from vsm.backends.vercel_blob import BlobRunStore, BlobTopicStore

        _log.info(
            "storage backend: Vercel Blob (BLOB_READ_WRITE_TOKEN is set, no "
            "database URL configured) — topics, runs and artifacts survive "
            "across invocations"
        )
        return BlobTopicStore(blob_token), BlobRunStore(blob_token)

    _log.info(
        "storage backend: SQLite+filesystem (no database URL and no "
        "BLOB_READ_WRITE_TOKEN configured) — writes live under var_dir and "
        "do NOT survive a serverless container being recycled"
    )
    return (
        TopicStore(settings.db_path),
        RunStore(settings.db_path, settings.var_dir),
    )
