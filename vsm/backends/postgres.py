"""Topics and runs on Postgres — the metadata half of the Vercel backend.

Same schema shape and the same guarded columns as the SQLite pair in
``vsm/topics/store.py`` and ``vsm/runs/store.py``, translated to Postgres's
own placeholder style (``%s``, not ``?``) and its own way of getting a
monotonic ordering column. Deliberately its own SQL rather than a shim over
the SQLite queries — see the module docstring on ``vsm/storage.py`` for why a
shim papering over ``?`` vs ``%s`` would be the defect, not the fix.

``seq`` is ``BIGSERIAL`` here, not ``SELECT COALESCE(MAX(seq),0)+1`` the way
the SQLite pair computes it. That subquery races under concurrent writers —
two inserts can read the same ``MAX(seq)`` before either commits and land on
the same next value — and a database sequence cannot, because ``nextval()``
is atomic. ``snapshots()`` ordering depends on ``seq`` being genuinely
monotonic (Task 4's ruling, restated in ``vsm/storage.py``), so this is
load-bearing, not a style preference.

Artifact storage (``write_artifact`` / ``read_artifact`` / ``artifacts_dir``)
is delegated to ``BlobArtifacts`` in ``vsm/backends/blob.py`` rather than
reimplemented here, for the same reason ``vsm/runs/store.py`` keeps run
metadata and run artifacts as two different mechanisms under one class: they
are genuinely different concerns (a row per run vs. a row per artifact) that
happen to share one public interface.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg

from vsm.backends.blob import BlobArtifacts
from vsm.errors import NoSuchRun, NoSuchTopic
from vsm.runs.model import RUN_MODES, RUN_STATUSES, Run
from vsm.topics.model import BANDS, Topic

__all__ = ["PostgresTopicStore", "PostgresRunStore"]

_SCHEMA_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quoted_schema(schema: str) -> str:
    if not _SCHEMA_NAME_RE.match(schema):
        raise ValueError(f"unsafe schema name: {schema!r}")
    return schema


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_TUPLE_FIELDS = ("competitors", "questions", "never_say")
_UPDATABLE = frozenset({
    "name", "therapeutic_area", "spend_band", "brand", "molecule",
    "competitors", "questions", "never_say",
})

_TOPIC_COLS = (
    "topic_id,name,therapeutic_area,spend_band,created_at,brand,molecule,"
    "competitors,questions,never_say"
)


class PostgresTopicStore:
    def __init__(self, dsn: str, schema: str = "public") -> None:
        self.dsn = dsn
        self.schema = _quoted_schema(schema)
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema}")
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.schema}.topics (
                    topic_id         TEXT PRIMARY KEY,
                    name             TEXT NOT NULL,
                    therapeutic_area TEXT NOT NULL,
                    spend_band       TEXT NOT NULL,
                    created_at       TEXT NOT NULL,
                    brand            TEXT,
                    molecule         TEXT,
                    competitors      TEXT NOT NULL DEFAULT '[]',
                    questions        TEXT NOT NULL DEFAULT '[]',
                    never_say        TEXT NOT NULL DEFAULT '[]',
                    seq              BIGSERIAL
                )
                """
            )

    def _conn(self) -> psycopg.Connection:
        return psycopg.connect(self.dsn, autocommit=True)

    @staticmethod
    def _row_to_topic(row: tuple) -> Topic:
        (topic_id, name, therapeutic_area, spend_band, created_at, brand,
         molecule, competitors, questions, never_say) = row
        return Topic(
            topic_id=topic_id, name=name, therapeutic_area=therapeutic_area,
            spend_band=spend_band, created_at=created_at, brand=brand,
            molecule=molecule,
            competitors=tuple(json.loads(competitors)),
            questions=tuple(json.loads(questions)),
            never_say=tuple(json.loads(never_say)),
        )

    def create(self, **kwargs: Any) -> Topic:
        if kwargs.get("spend_band") not in BANDS:
            raise KeyError(f"unknown spend band: {kwargs.get('spend_band')!r}")
        topic = Topic(
            topic_id=kwargs.pop("topic_id", None) or f"top-{uuid.uuid4().hex[:10]}",
            created_at=kwargs.pop("created_at", _now()),
            **kwargs,
        )
        with self._conn() as conn:
            conn.execute(
                f"INSERT INTO {self.schema}.topics ({_TOPIC_COLS}) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    topic.topic_id, topic.name, topic.therapeutic_area,
                    topic.spend_band, topic.created_at, topic.brand,
                    topic.molecule,
                    json.dumps(list(topic.competitors)),
                    json.dumps(list(topic.questions)),
                    json.dumps(list(topic.never_say)),
                ),
            )
        return topic

    def get(self, topic_id: str) -> Topic:
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT {_TOPIC_COLS} FROM {self.schema}.topics WHERE topic_id=%s",
                (topic_id,),
            ).fetchone()
        if row is None:
            raise NoSuchTopic(topic_id, rule="topics")
        return self._row_to_topic(row)

    def list(self) -> list[Topic]:
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT {_TOPIC_COLS} FROM {self.schema}.topics ORDER BY seq DESC"
            ).fetchall()
        return [self._row_to_topic(r) for r in rows]

    def update(self, topic_id: str, **fields: Any) -> Topic:
        current = self.get(topic_id)
        for key in fields:
            if key not in _UPDATABLE:
                raise KeyError(f"column {key!r} is not updatable")
        if "spend_band" in fields and fields["spend_band"] not in BANDS:
            raise KeyError(f"unknown spend band: {fields['spend_band']!r}")
        sets, values = [], []
        for key, value in fields.items():
            sets.append(f"{key}=%s")
            values.append(json.dumps(list(value)) if key in _TUPLE_FIELDS else value)
        if not sets:
            return current
        values.append(topic_id)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE {self.schema}.topics SET {','.join(sets)} WHERE topic_id=%s",
                values,
            )
        return self.get(topic_id)


_RUN_COLS = (
    "run_id,topic_id,mode,status,started_at,finished_at,cost_usd,"
    "parent_run_id,note"
)


class PostgresRunStore:
    def __init__(self, dsn: str, schema: str = "public") -> None:
        self.dsn = dsn
        self.schema = _quoted_schema(schema)
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema}")
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.schema}.runs (
                    run_id        TEXT PRIMARY KEY,
                    topic_id      TEXT NOT NULL,
                    mode          TEXT NOT NULL,
                    status        TEXT NOT NULL,
                    started_at    TEXT NOT NULL,
                    finished_at   TEXT,
                    cost_usd      DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                    parent_run_id TEXT,
                    note          TEXT NOT NULL DEFAULT '',
                    seq           BIGSERIAL
                )
                """
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS runs_topic ON {self.schema}.runs "
                "(topic_id, mode, seq)"
            )
        # Own SQL for the runs table above; artifacts are a different table
        # with its own schema, delegated rather than duplicated here.
        self._blobs = BlobArtifacts(dsn, schema=self.schema)

    def _conn(self) -> psycopg.Connection:
        return psycopg.connect(self.dsn, autocommit=True)

    @staticmethod
    def _to_run(row: tuple) -> Run:
        (run_id, topic_id, mode, status, started_at, finished_at, cost_usd,
         parent_run_id, note) = row
        return Run(
            run_id=run_id, topic_id=topic_id, mode=mode, status=status,
            started_at=started_at, finished_at=finished_at, cost_usd=cost_usd,
            parent_run_id=parent_run_id, note=note,
        )

    def start(
        self, topic_id: str, mode: str, parent_run_id: str | None = None
    ) -> Run:
        if mode not in RUN_MODES:
            raise KeyError(f"unknown run mode: {mode!r}")
        run = Run(
            run_id=f"{mode[:3]}-{uuid.uuid4().hex[:10]}", topic_id=topic_id,
            mode=mode, status="running", started_at=_now(),
            parent_run_id=parent_run_id,
        )
        with self._conn() as conn:
            conn.execute(
                f"INSERT INTO {self.schema}.runs "
                "(run_id,topic_id,mode,status,started_at,finished_at,"
                "cost_usd,parent_run_id,note) "
                "VALUES (%s,%s,%s,%s,%s,NULL,0.0,%s,'')",
                (run.run_id, topic_id, mode, "running", run.started_at, parent_run_id),
            )
        return run

    def finish(
        self, run_id: str, status: str, cost_usd: float, note: str = ""
    ) -> Run:
        if status not in RUN_STATUSES:
            raise KeyError(f"unknown run status: {status!r}")
        with self._conn() as conn:
            conn.execute(
                f"UPDATE {self.schema}.runs SET status=%s, finished_at=%s, "
                "cost_usd=%s, note=%s WHERE run_id=%s",
                (status, _now(), float(cost_usd), note, run_id),
            )
        return self.get(run_id)

    def get(self, run_id: str) -> Run:
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT {_RUN_COLS} FROM {self.schema}.runs WHERE run_id=%s",
                (run_id,),
            ).fetchone()
        if row is None:
            raise NoSuchRun(run_id, rule="runs")
        return self._to_run(row)

    def for_topic(self, topic_id: str, mode: str | None = None) -> list[Run]:
        sql = f"SELECT {_RUN_COLS} FROM {self.schema}.runs WHERE topic_id=%s"
        args: list[Any] = [topic_id]
        if mode:
            sql += " AND mode=%s"
            args.append(mode)
        sql += " ORDER BY seq ASC"
        with self._conn() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [self._to_run(r) for r in rows]

    def snapshots(self, topic_id: str) -> list[Run]:
        return [
            r for r in self.for_topic(topic_id, "mine") if r.status == "complete"
        ]

    def artifacts_dir(self, run_id: str) -> Path:
        return self._blobs.artifacts_dir(run_id)

    def write_artifact(self, run_id: str, name: str, payload: Any) -> Path:
        return self._blobs.write_artifact(run_id, name, payload)

    def read_artifact(self, run_id: str, name: str) -> Any:
        return self._blobs.read_artifact(run_id, name)
