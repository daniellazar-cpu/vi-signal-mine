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

Task 24 registered its Postgres backend by appending a
``pytest.param(its_factory, id="postgres")`` to ``STORE_FACTORIES`` below;
the Vercel Blob backend (``vsm/backends/vercel_blob.py``) is registered the
same way as ``id="blob"``. Every case in this file — round trips, unknown-id
errors, ``snapshots()`` ordering, the mode/status guards, the artifact
traversal guard, cross-instance persistence — then runs against that backend
unchanged. A factory registered this way must satisfy one contract of its
own: called twice with the *same* ``tmp_path``, it must return two
independent store objects that see each other's writes (e.g. by deriving a
connection string or blob root deterministically from ``tmp_path``), not two
objects backed by fresh, isolated storage.
"""

from __future__ import annotations

import hashlib
import os
import socket
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

#: The real `socket.socket.connect`, captured at import time — before
#: `tests/conftest.py`'s autouse `_no_real_sockets` fixture ever runs and
#: replaces it with a version that raises. The Blob factory below restores
#: this for the one test using it, because unlike `psycopg` (which reaches
#: libpq's own C sockets, invisible to this patch — why the Postgres factory
#: above needs no such restore) `httpx`'s default transport goes through
#: Python's own `socket` module and would otherwise be blocked by the same
#: guard that keeps the rest of this suite hermetic.
_REAL_SOCKET_CONNECT = socket.socket.connect

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


# The Vercel Blob factory. Skipped entirely (never added to
# STORE_FACTORIES, the same convention the Postgres factory above uses) when
# BLOB_READ_WRITE_TOKEN is not set, so the default suite stays hermetic —
# no test here ever makes a real network call unless a token was explicitly
# provided. Point it at a real Vercel Blob store to exercise it, e.g.:
#   BLOB_READ_WRITE_TOKEN=vercel_blob_rw_... pytest tests/test_storage_contract.py
_BLOB_TOKEN = (os.environ.get("BLOB_READ_WRITE_TOKEN") or "").strip()


def _blob_stores(
    tmp_path: Path,
) -> tuple[TopicStoreLike, RunStoreLike, ScrambleStartedAt]:
    from vsm.backends.vercel_blob import BlobRunStore, BlobTopicStore

    # Restore real networking for this one backend — see the module-level
    # note on `_REAL_SOCKET_CONNECT` for why this is needed here and not for
    # the Postgres factory above. `tests/conftest.py`'s autouse fixture
    # re-blocks it before the very next test regardless of this, so nothing
    # here leaks hermeticity into any test that does not use this factory.
    socket.socket.connect = _REAL_SOCKET_CONNECT

    # A root namespace derived deterministically from `tmp_path`, the same
    # technique the Postgres factory uses for its schema name: two calls
    # against the *same* `tmp_path` land in the same root (so they see each
    # other's writes, as the cross-instance-persistence cases require), and
    # two different `tmp_path`s — i.e. two different tests — land in
    # different roots and cannot collide. Real objects are left behind in
    # the Blob store under this `vsm-test/` prefix (there is no schema to
    # drop the way the Postgres factory's is, on a database nobody but tests
    # writes to); harmless scratch data, identifiable by that prefix if it
    # is ever worth sweeping.
    digest = hashlib.sha256(str(tmp_path).encode()).hexdigest()[:16]
    root = f"vsm-test/{digest}"
    topic_store = BlobTopicStore(_BLOB_TOKEN, root=root)
    run_store = BlobRunStore(_BLOB_TOKEN, root=root)

    def _scramble_started_at(run_id: str, started_at: str) -> None:
        # No public "rewrite a run" method, by design — reach the run's own
        # JSON blob directly and overwrite it, the equivalent of the raw
        # SQL `UPDATE` the other two factories use for the same hook.
        pathname = f"{root}/runs/{run_id}.json"
        data = run_store._ns.read_json(pathname)
        data["started_at"] = started_at
        run_store._ns.write_json(pathname, data)

    return topic_store, run_store, _scramble_started_at


STORE_FACTORIES = [pytest.param(_sqlite_stores, id="sqlite")]
if _HAS_PSYCOPG and _TEST_DB_URL:
    STORE_FACTORIES.append(pytest.param(_postgres_blob_stores, id="postgres"))
if _BLOB_TOKEN:
    STORE_FACTORIES.append(pytest.param(_blob_stores, id="blob"))


@pytest.fixture(params=STORE_FACTORIES)
def store_factory(request):
    return request.param


@pytest.fixture
def stores(store_factory, tmp_path):
    return store_factory(tmp_path)


@pytest.mark.skipif(not _BLOB_TOKEN, reason="BLOB_READ_WRITE_TOKEN not set")
def test_blob_seq_allocation_has_no_collisions_under_real_concurrent_writers(tmp_path):
    """Not part of the generic parametrised suite above — every other case
    in this file runs single-threaded, which cannot exercise the one thing
    ``BlobRunStore``'s ``_next_seq`` (``vsm/backends/vercel_blob.py``) exists
    to survive: two writers racing on the *same* counter blob. SQLite's
    ``seq`` column is safe by construction (one process, one file, a single
    writer at a time) and Postgres's ``BIGSERIAL`` is safe by the database
    engine's own guarantee — neither needed a test shaped like this one.
    Vercel Blob's compare-and-swap allocator is new, hand-built code, so its
    collision-freedom claim gets an actual concurrent race against the live
    API, not just the docstring's argument for why it should hold.

    Eight threads all call ``start()`` on the same topic at once; if two ever
    landed on the same ``seq``, two of the eight stored records would carry an
    identical value and this fails. That assertion is unchanged by how the
    ordinal is allocated, and is the reason this test survived the removal of
    the compare-and-swap counter it was originally written against: ordering
    breaks on a *tie*, whatever produced it. See ``_next_ordinal``'s docstring
    for why a CAS over a shared counter blob could not be made reliable on this
    backend, and ``tests/test_vercel_blob_stale_read.py`` for the hermetic
    version of this same property.

    Eight, not more: each ``start()`` here is a real HTTP write against the live
    store, and eight concurrent writers is already far more than this
    low-traffic internal tool sees in practice.
    """
    from concurrent.futures import ThreadPoolExecutor

    from vsm.backends.vercel_blob import BlobRunStore

    # Same restore the `_blob_stores` factory does, and for the same reason
    # (see the module-level note on `_REAL_SOCKET_CONNECT`) — this test does
    # not go through that factory, so the autouse hermetic-socket guard is
    # still in force here otherwise.
    socket.socket.connect = _REAL_SOCKET_CONNECT

    digest = hashlib.sha256(str(tmp_path).encode()).hexdigest()[:16]
    root = f"vsm-test/{digest}-concurrency"
    run_store = BlobRunStore(_BLOB_TOKEN, root=root)
    n = 8

    def _start_one(_: int) -> str:
        return run_store.start("top-concurrency", "mine").run_id

    with ThreadPoolExecutor(max_workers=n) as pool:
        run_ids = list(pool.map(_start_one, range(n)))

    assert len(set(run_ids)) == n, "two threads minted the same run_id"

    seqs = [
        run_store._ns.read_json(f"{root}/runs/{rid}.json")["seq"] for rid in run_ids
    ]
    assert len(set(seqs)) == n, f"seq collision under concurrency: {sorted(seqs)}"
    assert sorted(seqs) == list(range(1, n + 1)), f"gaps or duplicates: {sorted(seqs)}"


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


def test_prefetch_never_changes_what_a_read_returns(topic_store, run_store):
    """``prefetch_artifacts`` is an optimisation two backends implement and one
    does not, so the property that matters is that it is *invisible*: every
    read must return exactly what it would have returned without it, including
    the absences and including a read-after-write in the same request.

    In the shared suite because the two implementations are unrelated — one
    batches HTTP GETs, the other is a single SQL statement with an UNNEST — and
    each records absence separately, which is where this kind of cache goes
    wrong.
    """
    topic = topic_store.create(name="pf", therapeutic_area="", spend_band="probe")
    run = run_store.start(topic.topic_id, "mine")
    run_store.write_artifact(run.run_id, "signals.json", [{"a": 1}])
    run_store.write_artifact(run.run_id, "notes.md", "# hello")

    warm = getattr(run_store, "prefetch_artifacts", None)
    if warm is not None:
        warm([(run.run_id, "signals.json"), (run.run_id, "notes.md"),
              (run.run_id, "absent.json")])

    assert run_store.read_artifact(run.run_id, "signals.json") == [{"a": 1}]
    assert run_store.read_artifact(run.run_id, "notes.md") == "# hello"
    with pytest.raises(FileNotFoundError):
        run_store.read_artifact(run.run_id, "absent.json")

    # The resume logic does exactly this: probe, find nothing, write. A recorded
    # absence that outlives its own write would make the next read deny an
    # artifact that is now there.
    run_store.write_artifact(run.run_id, "absent.json", {"now": "here"})
    assert run_store.read_artifact(run.run_id, "absent.json") == {"now": "here"}


def test_prefetching_a_traversing_name_is_refused_not_raised(topic_store, run_store):
    """Warming is best-effort: a caller handing it a bad pair has not done
    anything wrong, and the read that follows reports the problem properly."""
    topic = topic_store.create(name="pf2", therapeutic_area="", spend_band="probe")
    run = run_store.start(topic.topic_id, "mine")

    warm = getattr(run_store, "prefetch_artifacts", None)
    if warm is None:
        pytest.skip("this backend does not implement prefetch_artifacts")
    warm([(run.run_id, "../escape.json")])           # must not raise
    with pytest.raises((ValueError, FileNotFoundError)):
        run_store.read_artifact(run.run_id, "../escape.json")


def test_for_topics_matches_for_topic_on_every_backend(topic_store, run_store):
    """``for_topics`` exists so the topics index costs a constant number of
    round trips instead of one per topic. It is therefore a *second*
    implementation of a query the app already had, on every backend — and the
    index reads its rows from the new one while every other screen reads from
    the old one, so a divergence shows up as the index quietly contradicting
    the pages it links to.

    Worth having in the shared suite rather than as a unit test with a fake:
    the Postgres version shipped with ``SELECT *`` where the table carries a
    ``seq`` column its row-mapper does not take, which unpacked ten values into
    nine. No fake would have caught it; the first run against a real database
    did.
    """
    ids = []
    for i in range(4):
        topic = topic_store.create(
            name=f"batched-{i}", therapeutic_area="", spend_band="probe"
        )
        ids.append(topic.topic_id)
        for _ in range(i):                      # 0, 1, 2, 3 runs
            run = run_store.start(topic.topic_id, "mine")
            run_store.finish(run.run_id, "complete", 0.0)

    batched = run_store.for_topics(ids)

    assert set(batched) == set(ids), "every id asked for must be a key"
    for tid in ids:
        assert batched[tid] == run_store.for_topic(tid), tid
    assert batched[ids[0]] == [], "a topic with no runs must map to an empty list"
    assert [len(batched[t]) for t in ids] == [0, 1, 2, 3]


def test_for_topics_ignores_topics_it_was_not_asked_about(topic_store, run_store):
    """A backend that has to read every run to find the ones it wants must not
    leak the others into the result."""
    keep = topic_store.create(name="keep", therapeutic_area="", spend_band="probe")
    other = topic_store.create(name="other", therapeutic_area="", spend_band="probe")
    for topic in (keep, other):
        run = run_store.start(topic.topic_id, "mine")
        run_store.finish(run.run_id, "complete", 0.0)

    batched = run_store.for_topics([keep.topic_id])
    assert set(batched) == {keep.topic_id}
    assert all(r.topic_id == keep.topic_id for r in batched[keep.topic_id])


def test_for_topics_of_nothing_is_an_empty_mapping(run_store):
    """The index renders an empty store, and a backend must not read anything
    to answer a question about no topics."""
    assert run_store.for_topics([]) == {}


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
    not just that each store class works in isolation.

    ``env={}`` is explicit rather than left to default to ``os.environ``:
    this test wants the SQLite fallback specifically, and depending on the
    ambient shell never happening to carry a database URL or a
    ``BLOB_READ_WRITE_TOKEN`` (plausible once Vercel Blob is in normal use)
    would make this test's outcome depend on who runs it and from where."""
    settings = Settings(var_dir=tmp_path)

    topic_store, run_store = open_stores(settings, env={})

    t = topic_store.create(name="A", therapeutic_area="gi", spend_band="probe")
    assert topic_store.get(t.topic_id) == t

    r = run_store.start(t.topic_id, "mine")
    assert run_store.get(r.run_id).status == "running"


def test_open_stores_picks_blob_over_sqlite_when_a_blob_token_is_set(tmp_path):
    """This task's backend selection, unconditional on any live token or
    network access: ``BlobTopicStore``/``BlobRunStore`` do no I/O in
    ``__init__`` (unlike ``PostgresTopicStore``, which connects and issues
    ``CREATE TABLE`` eagerly — see the next test for why that one needs a
    fake module instead), so this proves the branch was taken with nothing
    but a bogus token string."""
    from vsm.backends.vercel_blob import BlobRunStore, BlobTopicStore

    settings = Settings(var_dir=tmp_path)
    topic_store, run_store = open_stores(
        settings, env={"BLOB_READ_WRITE_TOKEN": "fake-token-for-selection-test"}
    )
    assert isinstance(topic_store, BlobTopicStore)
    assert isinstance(run_store, BlobRunStore)


def test_open_stores_picks_postgres_over_blob_when_both_are_configured(monkeypatch, tmp_path):
    """Postgres wins the tie when both a database URL and a Blob token
    resolve — see ``open_stores``'s own docstring for why: the more capable
    backend goes first, and the ordering has to be *some* fixed order.

    Proven without a live database or even ``psycopg`` installed: a fake
    module is installed at ``sys.modules["vsm.backends.postgres"]`` before
    calling ``open_stores``, so the lazy ``from vsm.backends.postgres import
    ...`` inside it resolves against dummy sentinel classes instead of ever
    dialing a real connection — keeping this hermetic regardless of whether
    the optional ``postgres`` extra happens to be installed in the
    environment running the suite.
    """
    import sys
    import types

    class DummyPostgresTopicStore:
        def __init__(self, dsn: str, schema: str = "public") -> None:
            self.dsn = dsn

    class DummyPostgresRunStore:
        def __init__(self, dsn: str, schema: str = "public") -> None:
            self.dsn = dsn

    fake_module = types.ModuleType("vsm.backends.postgres")
    fake_module.PostgresTopicStore = DummyPostgresTopicStore
    fake_module.PostgresRunStore = DummyPostgresRunStore
    monkeypatch.setitem(sys.modules, "vsm.backends.postgres", fake_module)

    settings = Settings(var_dir=tmp_path)
    topic_store, run_store = open_stores(
        settings,
        env={
            "DATABASE_URL": "postgresql://x/y",
            "BLOB_READ_WRITE_TOKEN": "fake-token-for-selection-test",
        },
    )
    assert isinstance(topic_store, DummyPostgresTopicStore)
    assert isinstance(run_store, DummyPostgresRunStore)
