"""Run metadata in SQLite; run artifacts as files under ``var/runs/<run_id>/``.

Artifacts are files rather than blobs because they are the deliverable — an
operator hands someone `provenance_appendix.md`, and a path is easier to hand
over than a row.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vsm.errors import NoSuchRun
from vsm.runs.model import Run

__all__ = ["RunStore"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    topic_id      TEXT NOT NULL,
    mode          TEXT NOT NULL,
    status        TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    cost_usd      REAL NOT NULL DEFAULT 0.0,
    parent_run_id TEXT,
    note          TEXT NOT NULL DEFAULT '',
    -- NOT NULL because snapshot ordering depends on it: history is a slice of a
    -- seq-ordered list, and a NULL here would sort unpredictably and silently
    -- drop a baseline.
    seq           INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_topic ON runs (topic_id, mode, seq);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunStore:
    def __init__(self, db_path: Path, var_dir: Path) -> None:
        self.db_path = Path(db_path)
        self.var_dir = Path(var_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        (self.var_dir / "runs").mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(_SCHEMA)
            c.commit()

    def _conn(self) -> closing[sqlite3.Connection]:
        """A connection that is committed **and closed**.

        ``sqlite3.Connection.__exit__`` commits or rolls back; it does not
        close. ``with self._conn() as c`` on a bare connection therefore leaks
        one per call, which surfaces as a ``ResourceWarning`` at finalisation —
        evidence, not noise. ``closing`` is the fix; silencing the warning is
        not.

        Note the shape this produces: ``closing`` yields the connection but
        does not commit, so every write path must commit explicitly.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return closing(conn)

    @staticmethod
    def _to_run(row: sqlite3.Row) -> Run:
        data = dict(row)
        data.pop("seq", None)
        return Run(**data)

    def start(self, topic_id: str, mode: str, parent_run_id: str | None = None) -> Run:
        run = Run(
            run_id=f"{mode[:3]}-{uuid.uuid4().hex[:10]}",
            topic_id=topic_id,
            mode=mode,  # type: ignore[arg-type]
            status="running",
            started_at=_now(),
            parent_run_id=parent_run_id,
        )
        with self._conn() as c:
            c.execute(
                "INSERT INTO runs (run_id,topic_id,mode,status,started_at,"
                "finished_at,cost_usd,parent_run_id,note,seq) VALUES "
                "(?,?,?,?,?,NULL,0.0,?,'',"
                "(SELECT COALESCE(MAX(seq),0)+1 FROM runs))",
                (run.run_id, topic_id, mode, "running", run.started_at, parent_run_id),
            )
            c.commit()
        self.artifacts_dir(run.run_id).mkdir(parents=True, exist_ok=True)
        return run

    def finish(self, run_id: str, status: str, cost_usd: float, note: str = "") -> Run:
        with self._conn() as c:
            c.execute(
                "UPDATE runs SET status=?, finished_at=?, cost_usd=?, note=? "
                "WHERE run_id=?",
                (status, _now(), float(cost_usd), note, run_id),
            )
            c.commit()
        return self.get(run_id)

    def get(self, run_id: str) -> Run:
        with self._conn() as c:
            row = c.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise NoSuchRun(run_id, rule="runs")
        return self._to_run(row)

    def for_topic(self, topic_id: str, mode: str | None = None) -> list[Run]:
        sql = "SELECT * FROM runs WHERE topic_id=?"
        args: list[Any] = [topic_id]
        if mode:
            sql += " AND mode=?"
            args.append(mode)
        sql += " ORDER BY seq ASC"
        with self._conn() as c:
            return [self._to_run(r) for r in c.execute(sql, args).fetchall()]

    def snapshots(self, topic_id: str) -> list[Run]:
        """Completed MINE runs, **oldest first** — every delta walks forward.

        Ordered by the monotonic ``seq`` column, not by ``started_at``. Callers
        establish "before" by position in this list; comparing timestamps would
        tie whenever two runs land in the same microsecond.
        """
        return [
            r for r in self.for_topic(topic_id, "mine") if r.status == "complete"
        ]

    def artifacts_dir(self, run_id: str) -> Path:
        return self.var_dir / "runs" / run_id

    def _artifact_path(self, run_id: str, name: str) -> Path:
        base = self.artifacts_dir(run_id).resolve()
        path = (base / name).resolve()
        if base != path.parent:
            raise ValueError(f"artifact name escapes the run directory: {name!r}")
        return path

    def write_artifact(self, run_id: str, name: str, payload: Any) -> Path:
        path = self._artifact_path(run_id, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, str):
            path.write_text(payload, encoding="utf-8")
        else:
            path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def read_artifact(self, run_id: str, name: str) -> Any:
        path = self._artifact_path(run_id, name)
        text = path.read_text(encoding="utf-8")
        return json.loads(text) if path.suffix == ".json" else text
