"""The storage contract, exercised once per backend.

This suite is the actual deliverable of spec D16, not ``vsm/storage.py``'s
``Protocol`` declarations. It is parametrised over a *store factory* — a
callable ``(tmp_path) -> (TopicStoreLike, RunStoreLike, scramble_started_at)``
— rather than over concrete store instances, for two reasons:

1. A factory can be called twice against the same ``tmp_path`` to build two
   independent store objects backed by the same underlying storage, which is
   what the cross-instance-persistence cases need. A fixture built from an
   already-constructed pair could not do that.
2. The ``snapshots()`` ordering guarantee — completed MINE runs, oldest
   first, by a monotonic sequence and never by comparing timestamps — has to
   be provable against *any* backend, not just SQLite's ``seq`` column. To
   prove it, a test needs to force wall-clock order to disagree with
   creation order after the fact. Reaching for ``sqlite3`` directly to do
   that would make the case SQLite-only and defeat the point of a shared
   suite, so the factory instead hands back a third element: a callable
   ``scramble_started_at(run_id, started_at_iso)`` that rewrites that one
   field through whatever means the backend has (a raw ``UPDATE`` for
   SQLite, the equivalent for Postgres) without going through the public
   store API — there is deliberately no public "rewrite a run" method.

Task 24 registers its Postgres-plus-blob backend by appending a
``pytest.param(its_factory, id="postgres")`` to ``STORE_FACTORIES`` below.
Every case in this file — round trips, unknown-id errors, ``snapshots()``
ordering, the mode/status guards, the artifact traversal guard,
cross-instance persistence — then runs against that backend unchanged. A
factory registered this way must satisfy one contract of its own: called
twice with the *same* ``tmp_path``, it must return two independent store
objects that see each other's writes (e.g. by deriving a connection string
or blob root deterministically from ``tmp_path``), not two objects backed by
fresh, isolated storage.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable

import pytest

from vsm.config import Settings
from vsm.errors import NoSuchRun, NoSuchTopic
from vsm.runs.store import RunStore
from vsm.storage import RunStoreLike, TopicStoreLike, open_stores
from vsm.topics.store import TopicStore

ScrambleStartedAt = Callable[[str, str], None]


def _sqlite_stores(
    tmp_path: Path,
) -> tuple[TopicStoreLike, RunStoreLike, ScrambleStartedAt]:
    db_path = tmp_path / "vsm.db"
    var_dir = tmp_path / "var"
    topic_store = TopicStore(db_path)
    run_store = RunStore(db_path, var_dir)

    def _scramble_started_at(run_id: str, started_at: str) -> None:
        with closing(sqlite3.connect(db_path)) as conn:
            conn.execute(
                "UPDATE runs SET started_at=? WHERE run_id=?", (started_at, run_id)
            )
            conn.commit()

    return topic_store, run_store, _scramble_started_at


# Task 24's Postgres+blob factory. Skipped entirely (never even added to
# STORE_FACTORIES, rather than added-then-skipped) when either `psycopg` is
# not installed — it is an optional extra, never a core dependency, see
# pyproject.toml — or no test database is configured. Point
# VSM_TEST_DATABASE_URL at a scratch Postgres to exercise it, e.g.:
#   VSM_TEST_DATABASE_URL=postgresql://postgres:pw@localhost:5432/postgres \
#       pytest tests/test_storage_contract.py
try:
    import psycopg  # noqa: F401

    _HAS_PSYCOPG = True
except ImportError:
    _HAS_PSYCOPG = False

_TEST_DB_URL = os.environ.get("VSM_TEST_DATABASE_URL")


def _postgres_blob_stores(
    tmp_path: Path,
) -> tuple[TopicStoreLike, RunStoreLike, ScrambleStartedAt]:
    from vsm.backends.postgres import PostgresRunStore, PostgresTopicStore

    # A real Postgres server is shared across every test in the run, unlike
    # SQLite's fresh file per `tmp_path`. A schema name derived deterministically
    # from `tmp_path` gives the same two guarantees the SQLite factory gets for
    # free: two calls against the *same* `tmp_path` land in the same schema (so
    # they see each other's writes, as the cross-instance-persistence cases
    # require), and two different `tmp_path`s — i.e. two different tests —
    # land in different schemas and cannot collide.
    digest = hashlib.sha256(str(tmp_path).encode()).hexdigest()[:16]
    schema = f"vsm_test_{digest}"
    topic_store = PostgresTopicStore(_TEST_DB_URL, schema=schema)
    run_store = PostgresRunStore(_TEST_DB_URL, schema=schema)

    def _scramble_started_at(run_id: str, started_at: str) -> None:
        with psycopg.connect(_TEST_DB_URL, autocommit=True) as conn:
            conn.execute(
                f"UPDATE {schema}.runs SET started_at=%s WHERE run_id=%s",
                (started_at, run_id),
            )

    return topic_store, run_store, _scramble_started_at


STORE_FACTORIES = [pytest.param(_sqlite_stores, id="sqlite")]
if _HAS_PSYCOPG and _TEST_DB_URL:
    STORE_FACTORIES.append(pytest.param(_postgres_blob_stores, id="postgres"))


@pytest.fixture(params=STORE_FACTORIES)
def store_factory(request):
    return request.param


@pytest.fixture
def stores(store_factory, tmp_path):
    return store_factory(tmp_path)


@pytest.fixture
def topic_store(stores) -> TopicStoreLike:
    return stores[0]


@pytest.fixture
def run_store(stores) -> RunStoreLike:
    return stores[1]


@pytest.fixture
def scramble_started_at(stores) -> ScrambleStartedAt:
    return stores[2]


# --- Protocol shape -----------------------------------------------------


def test_stores_satisfy_their_protocols(topic_store, run_store):
    assert isinstance(topic_store, TopicStoreLike)
    assert isinstance(run_store, RunStoreLike)


# --- Topics: create/read round-trip, unknown-id raising ------------------


def test_topic_create_and_read_round_trip(topic_store):
    t = topic_store.create(
        name="OIC pulse", therapeutic_area="gastroenterology", spend_band="standard"
    )
    assert topic_store.get(t.topic_id) == t
    assert t in topic_store.list()


def test_topic_get_unknown_raises(topic_store):
    with pytest.raises(NoSuchTopic):
        topic_store.get("nope")


# --- Runs: create/read round-trip, unknown-id raising ---------------------


def test_run_start_and_finish_round_trip(run_store):
    r = run_store.start("top-1", "mine")
    assert r.status == "running"
    done = run_store.finish(r.run_id, "complete", cost_usd=0.02, note="ok")
    assert done.status == "complete"
    assert run_store.get(r.run_id) == done


def test_run_get_unknown_raises(run_store):
    with pytest.raises(NoSuchRun):
        run_store.get("nope")


# --- Runs: mode/status are guarded, not persisted verbatim ----------------
#
# ``snapshots()`` filters on ``mode == "mine"`` and ``status == "complete"``.
# A misspelled value in either column does not raise on its own — it just
# makes the run permanently invisible to every downstream delta pass. Any
# backend has to refuse the write instead of persisting a typo.


def test_start_rejects_an_unknown_mode(run_store):
    with pytest.raises(KeyError):
        run_store.start("top-1", "miner")


def test_finish_rejects_an_unknown_status(run_store):
    r = run_store.start("top-1", "mine")
    with pytest.raises(KeyError):
        run_store.finish(r.run_id, "complet", cost_usd=0.0)


# --- snapshots(): ordering and filtering -----------------------------------


def test_snapshots_are_completed_mine_runs_oldest_first(run_store):
    a = run_store.start("top-1", "mine")
    run_store.finish(a.run_id, "complete", cost_usd=0.0)
    b = run_store.start("top-1", "mine")
    run_store.finish(b.run_id, "complete", cost_usd=0.0)
    still_running = run_store.start("top-1", "mine")
    other_mode = run_store.start("top-1", "insight")
    run_store.finish(other_mode.run_id, "complete", cost_usd=0.0)
    other_topic = run_store.start("top-2", "mine")
    run_store.finish(other_topic.run_id, "complete", cost_usd=0.0)

    ids = [r.run_id for r in run_store.snapshots("top-1")]

    assert ids == [a.run_id, b.run_id]
    assert still_running.run_id not in ids
    assert other_mode.run_id not in ids
    assert other_topic.run_id not in ids


def test_snapshots_order_survives_scrambled_timestamps(run_store, scramble_started_at):
    """Ordering must come from a monotonic sequence, not wall-clock time, on
    *any* backend — SQLite's ``seq`` column and Postgres's ``BIGSERIAL`` are
    different mechanisms that both have to satisfy this.

    Five runs created back-to-back would likely land in creation order even
    under a broken, timestamp-based ``snapshots()``, because clocks advance —
    that would pass this case for the wrong reason. Instead we create them,
    then rewrite ``started_at`` through the factory's own hook so timestamp
    order is the exact *reverse* of creation order, and assert the store
    still returns them in creation order. Only an implementation ordering by
    a monotonic counter survives this.
    """
    ids = []
    for _ in range(5):
        r = run_store.start("top-1", "mine")
        run_store.finish(r.run_id, "complete", cost_usd=0.0)
        ids.append(r.run_id)

    for i, run_id in enumerate(ids):
        reversed_ts = f"2000-01-01T00:00:{len(ids) - i:02d}+00:00"
        scramble_started_at(run_id, reversed_ts)

    assert [r.run_id for r in run_store.snapshots("top-1")] == ids


# --- Artifacts: write/read round-trip, and the traversal guard ------------


def test_artifact_write_and_read_round_trip(run_store):
    r = run_store.start("top-1", "mine")
    path = run_store.write_artifact(r.run_id, "signals.json", [{"signal_id": "sig-1"}])
    assert path.exists()
    assert run_store.read_artifact(r.run_id, "signals.json") == [{"signal_id": "sig-1"}]


def test_artifact_name_cannot_escape_the_run_directory(run_store):
    """A later blob-backed store needs the same rejection on its key, for the
    same reason a filesystem store needs it on a path: a caller-supplied name
    that is joined into a location without being checked is a traversal."""
    r = run_store.start("top-1", "mine")
    with pytest.raises(ValueError):
        run_store.write_artifact(r.run_id, "../../etc/passwd", {})


# --- Cross-instance persistence --------------------------------------------
#
# A single-instance round trip does not prove a write survives: it would
# still pass even if a write were buffered only in the connection's
# transaction state and never committed (SQLite) or never flushed (a
# hypothetical blob client). Building a second, independent store instance
# against the same location is what actually exercises that.


def test_topic_persists_across_store_instances(store_factory, tmp_path):
    topic_store_1, _, _ = store_factory(tmp_path)
    t = topic_store_1.create(name="persistent", therapeutic_area="gi", spend_band="probe")

    topic_store_2, _, _ = store_factory(tmp_path)
    assert topic_store_2.get(t.topic_id) == t


def test_run_persists_across_store_instances(store_factory, tmp_path):
    _, run_store_1, _ = store_factory(tmp_path)
    r = run_store_1.start("top-1", "mine")
    run_store_1.finish(r.run_id, "complete", cost_usd=0.01, note="done")

    _, run_store_2, _ = store_factory(tmp_path)
    reloaded = run_store_2.get(r.run_id)
    assert reloaded.status == "complete"
    assert reloaded.cost_usd == pytest.approx(0.01)


def test_artifact_persists_across_store_instances(store_factory, tmp_path):
    _, run_store_1, _ = store_factory(tmp_path)
    r = run_store_1.start("top-1", "mine")
    run_store_1.write_artifact(r.run_id, "signals.json", {"ok": True})

    _, run_store_2, _ = store_factory(tmp_path)
    assert run_store_2.read_artifact(r.run_id, "signals.json") == {"ok": True}


# --- open_stores(): the seam Task 24 replaces ------------------------------


def test_open_stores_returns_a_working_sqlite_pair(tmp_path):
    """Two lines of production code, but the exact seam a later backend
    swaps: this pins that ``open_stores`` wires a ``Settings`` into a pair
    that actually works together (both pointed at the same ``var_dir``),
    not just that each store class works in isolation."""
    settings = Settings(var_dir=tmp_path)

    topic_store, run_store = open_stores(settings)

    t = topic_store.create(name="A", therapeutic_area="gi", spend_band="probe")
    assert topic_store.get(t.topic_id) == t

    r = run_store.start(t.topic_id, "mine")
    assert run_store.get(r.run_id).status == "running"
