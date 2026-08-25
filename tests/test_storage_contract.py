"""The storage contract, exercised once per backend.

This suite is the actual deliverable of spec D16, not ``vsm/storage.py``'s
``Protocol`` declarations. It is parametrised over a *store factory* — a
callable ``(tmp_path) -> (TopicStoreLike, RunStoreLike)`` — rather than over
concrete store instances, for one reason: a factory can be called twice
against the same ``tmp_path`` to build two independent store objects backed
by the same underlying storage, which is what the cross-instance-persistence
case needs. A fixture built from an already-constructed pair could not do
that.

Task 24 registers its Postgres-plus-blob backend by appending a
``pytest.param(its_factory, id="postgres")`` to ``STORE_FACTORIES`` below.
Every case in this file — round trips, unknown-id errors, ``snapshots()``
ordering, the artifact traversal guard, cross-instance persistence — then
runs against that backend unchanged. A factory registered this way must
satisfy one contract of its own: called twice with the *same* ``tmp_path``,
it must return two independent store objects that see each other's writes
(e.g. by deriving a connection string or blob root deterministically from
``tmp_path`), not two objects backed by fresh, isolated storage.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vsm.errors import NoSuchRun, NoSuchTopic
from vsm.runs.store import RunStore
from vsm.storage import RunStoreLike, TopicStoreLike
from vsm.topics.store import TopicStore


def _sqlite_stores(tmp_path: Path) -> tuple[TopicStoreLike, RunStoreLike]:
    db_path = tmp_path / "vsm.db"
    var_dir = tmp_path / "var"
    return TopicStore(db_path), RunStore(db_path, var_dir)


# Task 24 appends its Postgres+blob factory here, e.g.:
#   STORE_FACTORIES.append(pytest.param(_postgres_blob_stores, id="postgres"))
STORE_FACTORIES = [pytest.param(_sqlite_stores, id="sqlite")]


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
    topic_store_1, _ = store_factory(tmp_path)
    t = topic_store_1.create(name="persistent", therapeutic_area="gi", spend_band="probe")

    topic_store_2, _ = store_factory(tmp_path)
    assert topic_store_2.get(t.topic_id) == t


def test_run_persists_across_store_instances(store_factory, tmp_path):
    _, run_store_1 = store_factory(tmp_path)
    r = run_store_1.start("top-1", "mine")
    run_store_1.finish(r.run_id, "complete", cost_usd=0.01, note="done")

    _, run_store_2 = store_factory(tmp_path)
    reloaded = run_store_2.get(r.run_id)
    assert reloaded.status == "complete"
    assert reloaded.cost_usd == pytest.approx(0.01)


def test_artifact_persists_across_store_instances(store_factory, tmp_path):
    _, run_store_1 = store_factory(tmp_path)
    r = run_store_1.start("top-1", "mine")
    run_store_1.write_artifact(r.run_id, "signals.json", {"ok": True})

    _, run_store_2 = store_factory(tmp_path)
    assert run_store_2.read_artifact(r.run_id, "signals.json") == {"ok": True}
