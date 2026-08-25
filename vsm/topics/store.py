"""Topics in SQLite. Tuple fields are stored as JSON arrays.

stdlib ``sqlite3`` on purpose: an ORM would be the tenth dependency for a
five-column table, and the schema here is small enough to read in one sitting.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vsm.errors import NoSuchTopic
from vsm.topics.model import BANDS, Topic

__all__ = ["TopicStore"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
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
    seq              INTEGER
);
"""

_TUPLE_FIELDS = ("competitors", "questions", "never_say")


class TopicStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_topic(row: sqlite3.Row) -> Topic:
        data: dict[str, Any] = dict(row)
        data.pop("seq", None)
        for field in _TUPLE_FIELDS:
            data[field] = tuple(json.loads(data[field]))
        return Topic(**data)

    def create(self, **kwargs: Any) -> Topic:
        if kwargs.get("spend_band") not in BANDS:
            raise KeyError(f"unknown spend band: {kwargs.get('spend_band')!r}")
        topic = Topic(
            topic_id=kwargs.pop("topic_id", None) or f"top-{uuid.uuid4().hex[:10]}",
            created_at=kwargs.pop(
                "created_at", datetime.now(timezone.utc).isoformat()
            ),
            **kwargs,
        )
        with self._conn() as c:
            c.execute(
                "INSERT INTO topics (topic_id,name,therapeutic_area,spend_band,"
                "created_at,brand,molecule,competitors,questions,never_say,seq) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,"
                "(SELECT COALESCE(MAX(seq),0)+1 FROM topics))",
                (
                    topic.topic_id,
                    topic.name,
                    topic.therapeutic_area,
                    topic.spend_band,
                    topic.created_at,
                    topic.brand,
                    topic.molecule,
                    json.dumps(list(topic.competitors)),
                    json.dumps(list(topic.questions)),
                    json.dumps(list(topic.never_say)),
                ),
            )
        return topic

    def get(self, topic_id: str) -> Topic:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM topics WHERE topic_id=?", (topic_id,)
            ).fetchone()
        if row is None:
            raise NoSuchTopic(topic_id, rule="topics")
        return self._row_to_topic(row)

    def list(self) -> list[Topic]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM topics ORDER BY seq DESC").fetchall()
        return [self._row_to_topic(r) for r in rows]

    def update(self, topic_id: str, **fields: Any) -> Topic:
        current = self.get(topic_id)
        if "spend_band" in fields and fields["spend_band"] not in BANDS:
            raise KeyError(f"unknown spend band: {fields['spend_band']!r}")
        sets, values = [], []
        for key, value in fields.items():
            sets.append(f"{key}=?")
            values.append(
                json.dumps(list(value)) if key in _TUPLE_FIELDS else value
            )
        if not sets:
            return current
        values.append(topic_id)
        with self._conn() as c:
            c.execute(f"UPDATE topics SET {','.join(sets)} WHERE topic_id=?", values)
        return self.get(topic_id)
