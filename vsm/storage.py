"""The storage contract: two ``Protocol``s a backend must satisfy (spec D16).

``vsm.topics.store.TopicStore`` and ``vsm.runs.store.RunStore`` are the
SQLite-plus-filesystem implementations that exist today, and are what
``open_stores`` returns. A later task adds a Postgres-plus-blob pair behind
the same two names, for the one Vercel constraint that matters here: only
``/tmp`` is writable there, and it belongs to a single invocation, so nothing
that must survive a request can go through a bare local file.

Declaring the ``Protocol``s costs about forty lines and buys a contract the
next backend has to satisfy — checked by the shared, parametrised suite in
``tests/test_storage_contract.py``, not by a resemblance to whatever this
first implementation happened to do. That suite, not this file, is where the
two backends are actually kept from drifting apart.

Deliberately no SQL dialect shim: ``TopicStore`` and ``RunStore`` write their
own SQL today, and the Postgres pair will write its own tomorrow. A shim
papering over ``?`` vs ``%s`` is where the subtle bugs live; two clear
implementations of a 5-column and a 9-column table are worth the
duplication.
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
    """Postgres-plus-blob when a database URL resolves, SQLite-plus-filesystem
    otherwise. ``env`` is injectable for tests; production callers (``vsm/app.py``)
    leave it at ``None`` and get ``os.environ``.

    Deliberately does not import ``vsm.backends.postgres`` / ``.blob`` at
    module scope — those import ``psycopg``, an optional extra never a core
    dependency, and the whole point of ``resolve_db_url`` returning ``None``
    is that a plain local install with no database configured must still work.

    Logs which backend it picked, at INFO, and names the *consequence* rather
    than the condition — the parent engine's equivalent warning went nowhere
    because nothing had configured a log handler, so the one signal saying
    "your writes are being lost" was silently discarded. Naming the
    consequence means even a bare, unconfigured root logger printing to
    stderr says something an operator would notice.
    """
    db_url = resolve_db_url(env if env is not None else os.environ)
    if db_url:
        from vsm.backends.postgres import PostgresRunStore, PostgresTopicStore

        _log.info(
            "storage backend: Postgres+blob (a database URL is configured) — "
            "topics, runs and artifacts survive across invocations"
        )
        return PostgresTopicStore(db_url), PostgresRunStore(db_url)

    _log.info(
        "storage backend: SQLite+filesystem (no database URL configured) — "
        "writes live under var_dir and do NOT survive a serverless "
        "container being recycled"
    )
    return (
        TopicStore(settings.db_path),
        RunStore(settings.db_path, settings.var_dir),
    )
