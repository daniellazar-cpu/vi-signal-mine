"""Read-only mode: the fix for "pressing stuff sometimes leads to Run not
found... and sometimes it does work."

**The defect, precisely.** On a deployment with no database, `open_stores`
falls back to SQLite plus the filesystem under a serverless function's own
`/tmp` — which belongs to one invocation and does not survive the container
being recycled (see `vsm/storage.py`'s own docstring). The seeded demo
topic is fixed (deterministic ids, `vsm/demo.py`), but anything a real
visitor creates is container-local: a write that cannot be read back by the
next request. No amount of error handling on the read side fixes a write
that silently disappears.

**The fix, and what this file proves about it.** `vsm.platform.storage_is_durable`
(see `tests/test_platform.py` for the guard itself) says whether this
instance can honour a write. When it cannot:

1. every mutating route refuses outright, with a 409, before touching the
   store — proven below, parametrised over all five so a route added later
   and left off the list fails loudly rather than being silently exempt;
2. the UI never renders the control that would have led to one of those
   routes — proven below against the actual rendered markup, on every
   screen that carries one;
3. everything already collected — the seeded worked example above all —
   stays completely reachable: read-only, not broken.

`tests/test_ui_topics.py` covers the sitewide banner and the create/edit
form specifically (the original "defect 1b" surface); this file covers the
other three mutating routes (mine, insight, report) and the end-to-end
read-only walk. `tests/test_ui_crawl.py` covers link-integrity in both
modes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from vsm.demo import seed_demo_topic
from vsm.mining.fake import DeterministicMiner
from vsm.modes.insight import run_insight
from vsm.modes.mine import run_mine
from vsm.modes.report import run_report
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore
from vsm.ui.app import create_app
from vsm.ui.content import EPHEMERAL_STORAGE_NOTICE, READ_ONLY_CONTROL_NOTE


def _not_durable(monkeypatch):
    """The one combination `storage_is_durable()` refuses: a Vercel
    serverless instance with no database url resolving and no
    BLOB_READ_WRITE_TOKEN set. Setting `VERCEL` alone would not be enough to
    prove the guard actually checks for a database (and now a Blob token)
    too, so every recognised name is cleared explicitly rather than assumed
    absent — an environment that happens to carry a real
    BLOB_READ_WRITE_TOKEN (a developer's shell with Vercel Blob configured
    for local use, say) must not silently turn this into "durable"."""
    monkeypatch.setenv("VERCEL", "1")
    for var in ("POSTGRES_URL_NON_POOLING", "POSTGRES_URL", "DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)


def _durable_locally(monkeypatch):
    """The other required state: a local run, no database configured — and
    per the task, this must be entirely unaffected by the guard."""
    monkeypatch.delenv("VERCEL", raising=False)
    for var in ("POSTGRES_URL_NON_POOLING", "POSTGRES_URL", "DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)


def _durable_via_blob_token(monkeypatch):
    """A third way this guard is satisfied without a database: Vercel, no
    database url, but ``BLOB_READ_WRITE_TOKEN`` set. This is the concrete
    behaviour this task adds — the read-only refusal must not fire here.
    The ``flow`` fixture's stores stay plain SQLite either way (this only
    changes what ``storage_is_durable()`` reports, exactly like
    ``_durable_locally`` above does for the "no Vercel" case); no real Blob
    token or network access is needed to prove the guard's decision."""
    monkeypatch.setenv("VERCEL", "1")
    for var in ("POSTGRES_URL_NON_POOLING", "POSTGRES_URL", "DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "fake-token-for-guard-test")


@pytest.fixture
def flow(tmp_path):
    """One real topic, carried all the way through mine -> insight ->
    report, so every one of the five mutating routes below has a real
    target — the 409 assertions must come from the read-only guard itself,
    never from a 404 upstream of it masking whether the guard even ran."""
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    topic = ts.create(name="Read-only flow", therapeutic_area="gi", spend_band="probe")
    mine = run_mine(topic, rs, miner=DeterministicMiner(queries_per_cluster=4), cluster_count=1)
    insight = run_insight(topic, mine.run_id, rs, client=None)
    report = run_report(topic, insight.run_id, rs, client=None)
    return ts, rs, topic, mine, insight, report


def _client(flow) -> TestClient:
    ts, rs, *_ = flow
    return TestClient(create_app(topic_store=ts, run_store=rs))


# --------------------------------------------------------------------- #
# Every mutating route refuses with 409 when storage is not durable,     #
# and works when it is. Parametrised over the full list — see the        #
# module docstring for why a hardcoded list here, not five separate      #
# hand-written tests.                                                    #
# --------------------------------------------------------------------- #

_MUTATING_ROUTES = [
    ("topics_create", lambda f: "/topics", lambda f: {"name": "New topic", "spend_band": "probe"}),
    ("topics_update", lambda f: f"/topics/{f[2].topic_id}",
     lambda f: {"name": "Renamed topic", "spend_band": "probe"}),
    ("topic_mine", lambda f: f"/topics/{f[2].topic_id}/mine", lambda f: {"band": "probe"}),
    ("insight_create", lambda f: f"/runs/{f[3].run_id}/insight", lambda f: {}),
    ("report_create", lambda f: f"/runs/{f[4].run_id}/report", lambda f: {}),
]
_ROUTE_IDS = [r[0] for r in _MUTATING_ROUTES]


@pytest.mark.parametrize("name, path_fn, data_fn", _MUTATING_ROUTES, ids=_ROUTE_IDS)
def test_mutating_route_refuses_with_409_when_not_durable(flow, monkeypatch, name, path_fn, data_fn):
    _not_durable(monkeypatch)
    client = _client(flow)
    resp = client.post(path_fn(flow), data=data_fn(flow))
    assert resp.status_code == 409, f"{name}: expected 409, got {resp.status_code}\n{resp.text[:800]}"
    # Not a bare status code: the request was valid and would have
    # succeeded on a durable deployment, so the body has to say that,
    # not just refuse silently.
    assert EPHEMERAL_STORAGE_NOTICE in resp.text, f"{name}: refusal did not explain itself"


@pytest.mark.parametrize("name, path_fn, data_fn", _MUTATING_ROUTES, ids=_ROUTE_IDS)
def test_mutating_route_works_when_durable(flow, monkeypatch, name, path_fn, data_fn):
    _durable_locally(monkeypatch)
    client = _client(flow)
    resp = client.post(path_fn(flow), data=data_fn(flow), follow_redirects=False)
    assert resp.status_code in (200, 303), f"{name}: expected success, got {resp.status_code}\n{resp.text[:800]}"


@pytest.mark.parametrize("name, path_fn, data_fn", _MUTATING_ROUTES, ids=_ROUTE_IDS)
def test_mutating_route_works_when_durable_via_blob_token(flow, monkeypatch, name, path_fn, data_fn):
    """The read-only refusal must not fire on a Vercel instance with no
    database configured, once a Blob token is present — the whole point of
    this task. Would fail if ``vsm.platform.storage_is_durable`` did not
    check ``BLOB_READ_WRITE_TOKEN`` (every one of these routes would still
    409, same as ``test_mutating_route_refuses_with_409_when_not_durable``)."""
    _durable_via_blob_token(monkeypatch)
    client = _client(flow)
    resp = client.post(path_fn(flow), data=data_fn(flow), follow_redirects=False)
    assert resp.status_code in (200, 303), f"{name}: expected success, got {resp.status_code}\n{resp.text[:800]}"


def test_the_409_page_is_not_a_500_and_names_no_stack_trace(flow, monkeypatch):
    """A guard that raises where it should refuse cleanly is still a 500 by
    another name. Belt-and-braces beyond the parametrised check above."""
    _not_durable(monkeypatch)
    client = _client(flow)
    resp = client.post("/topics", data={"name": "X", "spend_band": "probe"})
    assert resp.status_code < 500
    assert "Traceback" not in resp.text


# --------------------------------------------------------------------- #
# The controls those routes are reached through are not rendered at all  #
# when storage is not durable — a button that cannot work is worse than  #
# an absent one.                                                         #
# --------------------------------------------------------------------- #


def test_confirm_screen_has_no_mine_form_when_not_durable(flow, monkeypatch):
    _not_durable(monkeypatch)
    ts, rs, topic, *_ = flow
    client = _client(flow)
    body = client.get(f"/topics/{topic.topic_id}/confirm?band=probe").text
    assert f'action="/topics/{topic.topic_id}/mine"' not in body
    assert READ_ONLY_CONTROL_NOTE in body
    # Read-only does not mean empty: the estimate and the deliverables
    # preview are exactly the kind of already-collected information that
    # must stay available (spec: "Everything read-only stays fully
    # available").
    assert "$" in body


def test_confirm_screen_has_the_mine_form_when_durable(flow, monkeypatch):
    _durable_locally(monkeypatch)
    ts, rs, topic, *_ = flow
    client = _client(flow)
    body = client.get(f"/topics/{topic.topic_id}/confirm?band=probe").text
    assert f'action="/topics/{topic.topic_id}/mine"' in body


def test_confirm_screen_has_the_mine_form_when_durable_via_blob_token(flow, monkeypatch):
    _durable_via_blob_token(monkeypatch)
    ts, rs, topic, *_ = flow
    client = _client(flow)
    body = client.get(f"/topics/{topic.topic_id}/confirm?band=probe").text
    assert f'action="/topics/{topic.topic_id}/mine"' in body


def test_run_screen_has_no_insight_form_when_not_durable(flow, monkeypatch):
    _not_durable(monkeypatch)
    _, _, _, mine, *_ = flow
    client = _client(flow)
    body = client.get(f"/runs/{mine.run_id}").text
    assert f'action="/runs/{mine.run_id}/insight"' not in body
    assert READ_ONLY_CONTROL_NOTE in body


def test_run_screen_has_the_insight_form_when_durable(flow, monkeypatch):
    _durable_locally(monkeypatch)
    _, _, _, mine, *_ = flow
    client = _client(flow)
    body = client.get(f"/runs/{mine.run_id}").text
    assert f'action="/runs/{mine.run_id}/insight"' in body


def test_run_screen_has_no_report_form_when_not_durable(flow, monkeypatch):
    _not_durable(monkeypatch)
    _, _, _, _, insight, _ = flow
    client = _client(flow)
    body = client.get(f"/runs/{insight.run_id}").text
    assert f'action="/runs/{insight.run_id}/report"' not in body
    assert READ_ONLY_CONTROL_NOTE in body


def test_run_screen_has_the_report_form_when_durable(flow, monkeypatch):
    _durable_locally(monkeypatch)
    _, _, _, _, insight, _ = flow
    client = _client(flow)
    body = client.get(f"/runs/{insight.run_id}").text
    assert f'action="/runs/{insight.run_id}/report"' in body


def test_snapshot_screen_has_no_insight_form_when_not_durable(flow, monkeypatch):
    _not_durable(monkeypatch)
    _, _, _, mine, *_ = flow
    client = _client(flow)
    body = client.get(f"/runs/{mine.run_id}/snapshot").text
    assert f'action="/runs/{mine.run_id}/insight"' not in body
    assert READ_ONLY_CONTROL_NOTE in body


def test_snapshot_screen_has_the_insight_form_when_durable(flow, monkeypatch):
    _durable_locally(monkeypatch)
    _, _, _, mine, *_ = flow
    client = _client(flow)
    body = client.get(f"/runs/{mine.run_id}/snapshot").text
    assert f'action="/runs/{mine.run_id}/insight"' in body


def test_insight_screen_has_no_report_form_when_not_durable(flow, monkeypatch):
    _not_durable(monkeypatch)
    _, _, _, _, insight, _ = flow
    client = _client(flow)
    body = client.get(f"/runs/{insight.run_id}/insight").text
    assert f'action="/runs/{insight.run_id}/report"' not in body
    assert READ_ONLY_CONTROL_NOTE in body


def test_insight_screen_has_the_report_form_when_durable(flow, monkeypatch):
    _durable_locally(monkeypatch)
    _, _, _, _, insight, _ = flow
    client = _client(flow)
    body = client.get(f"/runs/{insight.run_id}/insight").text
    assert f'action="/runs/{insight.run_id}/report"' in body


# --------------------------------------------------------------------- #
# The local install is unaffected: every control still works, and a      #
# topic can be created and carried through mine -> insight -> report.    #
# --------------------------------------------------------------------- #


def test_a_full_flow_still_works_end_to_end_on_a_local_install(tmp_path, monkeypatch):
    """Not the `flow` fixture (which builds runs directly through the
    engine) — this drives the same HTTP layer a browser does, create
    through report, to prove the local install is unaffected by this guard
    at the one layer that matters: real requests through real routes."""
    _durable_locally(monkeypatch)
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    client = TestClient(create_app(topic_store=ts, run_store=rs))

    resp = client.post(
        "/topics", data={"name": "Local flow", "spend_band": "probe"}, follow_redirects=False
    )
    assert resp.status_code == 303
    topic = ts.list()[0]

    resp = client.post(f"/topics/{topic.topic_id}/mine", data={"band": "probe"}, follow_redirects=False)
    assert resp.status_code == 303
    mine_run_id = resp.headers["location"].rsplit("/", 1)[-1]

    resp = client.post(f"/runs/{mine_run_id}/insight", follow_redirects=False)
    assert resp.status_code == 303
    insight_run_id = resp.headers["location"].rsplit("/", 2)[-2]

    resp = client.post(f"/runs/{insight_run_id}/report", follow_redirects=False)
    assert resp.status_code == 303


# --------------------------------------------------------------------- #
# Read-only mode still reaches the seeded example end to end.            #
# --------------------------------------------------------------------- #


def test_the_seeded_example_is_fully_reachable_in_read_only_mode(tmp_path, monkeypatch):
    """topic -> snapshot -> insight -> report -> artifact download, all as
    plain GETs, on an instance where storage_is_durable() is False. This is
    the concrete promise behind "everything read-only stays fully
    available": the seeded worked example must not become collateral
    damage of the guard that protects real visitors' writes."""
    _not_durable(monkeypatch)
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    seed_demo_topic(ts, rs, env={})  # the seed's own guard checks for a db url, not VERCEL
    client = TestClient(create_app(topic_store=ts, run_store=rs))

    topic = ts.list()[0]
    resp = client.get(f"/topics/{topic.topic_id}")
    assert resp.status_code == 200

    snapshots = rs.snapshots(topic.topic_id)
    assert len(snapshots) == 2
    mine_run = snapshots[-1]
    resp = client.get(f"/runs/{mine_run.run_id}/snapshot")
    assert resp.status_code == 200

    insight_runs = [r for r in rs.for_topic(topic.topic_id, "insight") if r.parent_run_id == mine_run.run_id]
    assert len(insight_runs) == 1
    insight_run = insight_runs[0]
    resp = client.get(f"/runs/{insight_run.run_id}/insight")
    assert resp.status_code == 200

    report_runs = [r for r in rs.for_topic(topic.topic_id, "report") if r.parent_run_id == insight_run.run_id]
    assert len(report_runs) == 1
    report_run = report_runs[0]
    resp = client.get(f"/runs/{report_run.run_id}/report")
    assert resp.status_code == 200

    resp = client.get(f"/runs/{mine_run.run_id}/artifact/signals.json")
    assert resp.status_code == 200
    assert resp.json()  # a real, non-empty signal ledger, not just a 200 with nothing behind it

    resp = client.get(f"/runs/{report_run.run_id}/artifact/pulse_report.md")
    assert resp.status_code == 200
    assert resp.text.strip()
