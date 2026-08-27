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
import time
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


def read_required(store: Any, run_id: str, name: str,
                  *, attempts: int = 6, base_delay: float = 0.25) -> Any:
    """An artifact the caller **knows** must exist, read through a transient
    absence.

    Not a general retry, and deliberately not built into ``read_artifact``: a
    great deal of this app reads artifacts whose absence is a legitimate answer
    — ``_existing_artifact`` in ``vsm/modes/insight.py`` uses a failed read to
    decide whether a resumed run may skip a pass, and the deliverable cards
    probe ten names per run of which several are genuinely absent. Retrying
    those would add seconds to every page in exchange for nothing. So the
    distinction lives at the call site, where it is known.

    **Why this is needed at all.** On the Vercel Blob backend a blob is not
    readable from every edge the instant its write returns. Measured on
    production: the report step failed roughly half the time with "No snapshot
    to report on", while the very artifacts it could not read returned 200 to an
    external check made immediately afterwards — from a different region than
    the one the function ran in. The write had landed and simply was not visible
    yet where the reader stood. So the read was correct, the conclusion drawn
    from it ("this artifact is gone, tell the user to mine again") was not.

    Only ``vsm/backends/vercel_blob.py`` has this property, and it is the only
    thing that declares ``reads_may_lag``. The filesystem store reads a file it
    just wrote, and ``vsm/backends/blob.py`` — despite the name — is a
    key-value *table* on the same Postgres database, so both read their own
    writes and take the single-attempt path.

    Bounded on purpose. Six attempts with full exponential backoff is about 7.75
    seconds in the worst case, comfortably inside a serverless function's
    ceiling, and a genuine absence still surfaces as ``FileNotFoundError`` — it
    is just slower to conclude, which is the right trade when the alternative is
    telling someone their data is lost while it is sitting in the store.
    """
    # A backend that reads its own writes has nothing to wait for: there, a
    # failed read means the artifact is genuinely absent, and retrying only
    # makes that conclusion slower — and taxes every test that deletes an
    # artifact on purpose. Opt in, so the cost sits with the one backend that
    # has the property.
    if not getattr(store, "reads_may_lag", False):
        return store.read_artifact(run_id, name)

    last: FileNotFoundError | None = None
    for attempt in range(attempts):
        try:
            return store.read_artifact(run_id, name)
        except FileNotFoundError as exc:
            last = exc
            if attempt < attempts - 1:
                time.sleep(base_delay * (2 ** attempt))
    assert last is not None  # the loop cannot exit without raising or returning
    raise last
