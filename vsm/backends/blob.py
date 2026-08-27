"""Artifacts as rows in Postgres — the blob half of the Vercel backend.

The dependency list this app is allowed to carry (see ``pyproject.toml``) has
no dedicated blob-storage SDK on it, so this is not a client for one; it is a
key-value table living on the same Postgres database ``vsm/backends/postgres.py``
already adopted for topics and runs, reached through its own SQL rather than
a shared connection helper — the same "no dialect shim" call the spec makes
for the topics/runs pair applies here too, one table further.

Same three-method surface as the filesystem writer in ``vsm/runs/store.py`` —
``write_artifact`` / ``read_artifact`` / ``artifacts_dir`` — traded for the
same behaviour: a JSON-shaped payload round-trips through ``json.dumps`` /
``json.loads``, a string payload is stored and returned verbatim, and a
missing artifact raises ``FileNotFoundError`` exactly like a missing file
would, because every caller (``vsm/ui/app.py``, ``vsm/modes/*``) already
catches that one exception name.

**The traversal guard carries across.** ``RunStore._artifact_path`` rejects a
filesystem path that a caller-supplied name resolves outside its run
directory. A key-value store has no filesystem to escape, but the same bug
has the same shape: a name joined into a key with no check is exactly as
traversable as a name joined into a path with no check. ``_validated_key``
applies the identical rule — ``posixpath.normpath`` the joined key, then
require its directory component to be exactly the run id — so
``"../../etc/passwd"`` and an absolute name are both rejected the same way
``RunStore`` rejects them, checked in the shared contract suite rather than
in a backend-specific test.
"""

from __future__ import annotations

import json
import posixpath
import re
from pathlib import PurePosixPath
from typing import Any

import psycopg

__all__ = ["BlobArtifacts"]

_SCHEMA_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quoted_schema(schema: str) -> str:
    # Schema names cannot be bound as SQL parameters (they are identifiers,
    # not values), so this is the guard against ever interpolating something
    # unsafe into DDL/DML — every caller in this codebase derives the schema
    # deterministically (a hash, or the literal default), never from
    # unsanitised input, but the check stays cheap insurance against a future
    # caller that does not.
    if not _SCHEMA_NAME_RE.match(schema):
        raise ValueError(f"unsafe schema name: {schema!r}")
    return schema


#: Distinguishes "looked it up and it is not there" from "not looked up yet".
#: Recording the absence matters as much as recording a hit: the deliverable
#: cards probe ten names per run and several are legitimately missing, so
#: without this those turn back into a query each.
_ABSENT = object()
_UNSET = object()


class BlobArtifacts:
    """One Postgres table, keyed by ``(run_id, name)``."""

    def __init__(self, dsn: str, schema: str = "public") -> None:
        self.dsn = dsn
        self.schema = _quoted_schema(schema)
        #: Request-scoped, ``(run_id, name)`` -> payload or `_ABSENT`. Warmed by
        #: `prefetch_artifacts`, cleared by `begin_request`.
        self._warm: dict[tuple[str, str], Any] = {}
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema}")
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.schema}.artifacts (
                    run_id     TEXT NOT NULL,
                    name       TEXT NOT NULL,
                    payload    TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (run_id, name)
                )
                """
            )
        self._path_cls = _bound_blob_path_class(self)

    def _conn(self) -> psycopg.Connection:
        return psycopg.connect(self.dsn, autocommit=True)

    @staticmethod
    def _validated_key(run_id: str, name: str) -> None:
        candidate = posixpath.normpath(posixpath.join(run_id, name))
        if posixpath.dirname(candidate) != run_id:
            raise ValueError(f"artifact name escapes the run directory: {name!r}")

    def key_exists(self, run_id: str, name: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT 1 FROM {self.schema}.artifacts WHERE run_id=%s AND name=%s",
                (run_id, name),
            ).fetchone()
        return row is not None

    def artifacts_dir(self, run_id: str) -> Any:
        return self._path_cls(run_id)

    def write_artifact(self, run_id: str, name: str, payload: Any) -> Any:
        self._validated_key(run_id, name)
        text = payload if isinstance(payload, str) else json.dumps(
            payload, indent=2, sort_keys=True
        )
        with self._conn() as conn:
            conn.execute(
                f"INSERT INTO {self.schema}.artifacts (run_id, name, payload) "
                "VALUES (%s,%s,%s) ON CONFLICT (run_id, name) "
                "DO UPDATE SET payload=EXCLUDED.payload, updated_at=now()",
                (run_id, name, text),
            )
        # A warm entry for this key is now wrong — including a recorded absence,
        # which is the common case here: the resume logic checks whether an
        # artifact exists and writes it when it does not.
        self._warm.pop((run_id, name), None)
        return self._path_cls(run_id) / name

    def delete_for_runs(self, run_ids: "list[str]") -> None:
        """Every artifact belonging to any of these runs, in one statement.

        Takes the whole list rather than one run at a time because deleting a
        topic means deleting all of its runs, and a round trip per run is a
        round trip too many.
        """
        if not run_ids:
            return
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            conn.execute(
                f"DELETE FROM {self.schema}.artifacts WHERE run_id = ANY(%s)",
                (list(run_ids),),
            )

    def begin_request(self) -> None:
        """Drop the request-scoped artifact map. Called once per HTTP request.

        Not a cache with a lifetime: it is correct only inside one request, and
        clearing it is the caller's job (``vsm/ui/app.py``'s middleware), not a
        timer's.
        """
        self._warm.clear()

    def prefetch_artifacts(self, pairs: "list[tuple[str, str]]") -> None:
        """Fetch many artifacts in **one** query.

        The pages that render deliverable cards ask for up to ten artifacts per
        run, several of which are legitimately absent, and a run/insight/report
        page was paying a query for each. Same shape as the blob backend's
        method of the same name — purely an optimisation, safe to skip, and
        ``read_artifact`` behaves identically whether or not it ran.

        A ``(run_id, name)`` pair that does not exist is recorded as absent
        rather than omitted, so the read that follows does not go back to the
        database to be told the same thing again.
        """
        keys = []
        for run_id, name in pairs:
            try:
                self._validated_key(run_id, name)
            except ValueError:
                continue
            if (run_id, name) not in self._warm:
                keys.append((run_id, name))
        if not keys:
            return
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT run_id, name, payload FROM {self.schema}.artifacts "
                "WHERE (run_id, name) IN (SELECT * FROM UNNEST(%s::text[], %s::text[]))",
                ([k[0] for k in keys], [k[1] for k in keys]),
            ).fetchall()
        found = {(r[0], r[1]): r[2] for r in rows}
        for key in keys:
            self._warm[key] = found.get(key, _ABSENT)

    def read_artifact(self, run_id: str, name: str) -> Any:
        self._validated_key(run_id, name)
        warm = self._warm.get((run_id, name), _UNSET)
        if warm is _UNSET:
            with self._conn() as conn:
                row = conn.execute(
                    f"SELECT payload FROM {self.schema}.artifacts WHERE run_id=%s AND name=%s",
                    (run_id, name),
                ).fetchone()
            warm = _ABSENT if row is None else row[0]
        if warm is _ABSENT:
            raise FileNotFoundError(f"no artifact named {name!r} on run {run_id!r}")
        text = warm
        return json.loads(text) if name.endswith(".json") else text


def _bound_blob_path_class(store: "BlobArtifacts") -> type[PurePosixPath]:
    """A ``Path``-shaped handle over a blob key.

    ``vsm.runs.store.RunStore.artifacts_dir`` returns a real filesystem
    ``Path``, and ``vsm/ui/app.py`` calls ``.exists()`` / ``/`` / ``.parent`` /
    ``.is_file()`` / ``.resolve()`` on what it gets back without knowing which
    backend produced it. A plain string cannot stand in for that. Binding the
    store as a *class* attribute (rather than threading it through
    ``__init__``) is what lets ``PurePosixPath``'s own ``/`` and ``.parent``
    machinery build further instances of this same bound subclass for free —
    both call ``type(self)(...)`` with plain path segments internally, so a
    subclass whose ``__init__`` demanded an extra argument would break the
    moment either was used.

    Existence is a live query against the table, not a local cache, so it
    reads the same truth from any process — which matters here specifically
    because the whole point of this backend is that no process-local state is
    the source of truth.
    """

    class _BoundBlobPath(PurePosixPath):
        _store = store

        def exists(self) -> bool:
            run_id, sep, name = str(self).partition("/")
            return sep != "" and self._store.key_exists(run_id, name)

        def is_file(self) -> bool:
            return self.exists()

        def resolve(self, strict: bool = False) -> "_BoundBlobPath":
            # No filesystem beneath this to resolve against; the guard that
            # would otherwise live in `.resolve()` normalising `..` already
            # ran in `_validated_key` at write/read time, and any `..` left
            # in an unvalidated path (e.g. one built by `vsm/ui/app.py`'s own
            # traversal check before a write ever happens) makes `.parent`
            # structurally disagree with the run root without needing
            # normalisation — see the artifact_download route.
            return self

    return _BoundBlobPath
