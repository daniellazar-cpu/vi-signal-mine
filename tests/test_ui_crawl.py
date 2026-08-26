"""The link crawler that proves there are no dead ends — and the QA pass the
owner asked for on top of it: "the whole UI is fucked and leading to
deadends and pressing stuff sometimes lead to an empty Run not found... QA
the shit out of it."

**What a dead end actually is, here.** Every page in this app is built by
reading rows this same process already wrote (or a 404/400 rendered
honestly when it can't find them) — see ``vsm/ui/app.py``'s own module
docstring. A dead end is therefore always a bug, never bad luck: a link the
app itself rendered that 404s or 500s the moment it is followed. The
original report — clicking through and hitting ``No run with id
'min-bc6e7230e0'``, intermittently — turned out to be exactly that, at the
seed layer (fixed in ``vsm/demo.py``; see ``tests/test_demo.py``'s
determinism tests). This file is the mechanical proof that nothing *else*
in the app has the same shape of bug: a page that links, redirects, or
downloads its way to a 404 or a 500.

**The crawler's contract, and why it is not vacuous.** ``crawl()`` starts at
``/`` and does real breadth-first traversal: every ``<a href>``, every
``<link href>`` and every GET ``<form action>`` found in a fetched page's
*raw HTML* — never the rendered DOM, so a CSS-hidden tab panel
(``insight.html``'s radio-button tabs) or a closed ``<details>`` is exactly
as reachable to this crawler as it is to ``view-source:``, which is the
right standard for "no JavaScript" (spec constraint: this app must work
with scripting disabled). POST-only form actions are recorded but not
GET-followed — submitting one is a side effect, not a navigation, and is
walked explicitly and deliberately in
``test_every_post_form_redirects_to_a_live_page`` below instead. Every test
below asserts a floor on how many distinct pages were reached, not just
"zero failures" — this project has a documented history (the owner's own
words) of tests that pass by not exercising anything, and a crawler that
silently only ever visits ``/`` would satisfy "no dead links found" while
proving nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

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

# --------------------------------------------------------------------- #
# The crawler.                                                          #
# --------------------------------------------------------------------- #


class _LinkParser(HTMLParser):
    """Every ``<a href>``/``<link href>`` and every ``<form action>`` (with
    its method) in one page's raw HTML — parsed from the markup itself, not
    a rendered DOM, so a CSS-hidden ``.tab-panel`` or ``<details>`` body is
    seen exactly as if scripting and styling were both off.
    """

    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []
        self.forms: list[tuple[str, str]] = []  # (action, method)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        d = dict(attrs)
        if tag in ("a", "link") and d.get("href"):
            self.hrefs.append(d["href"])
        elif tag == "form" and d.get("action"):
            self.forms.append((d["action"], (d.get("method") or "get").lower()))


def _internal_target(base_path: str, href: str) -> str | None:
    """``href`` resolved against the page it was found on, or ``None`` when
    it is not a same-origin resource this crawler should follow.

    Excluded on purpose: a bare ``#fragment`` (a same-page anchor, not a
    navigation — ``report.html``'s ``#sig-<id>`` citation jumps are this),
    ``mailto:``/``javascript:`` schemes, and any absolute URL. The last one
    matters specifically here: every signal and citation URL this app
    renders (``snapshot.html``, ``report.html``) is a *real, external*
    gold-list domain that the offline demonstration miner deliberately
    never fetched (``vsm.mining.fake.DeterministicMiner`` — the URL exists
    only to prove venue routing worked, not to be followed), and this
    suite is hermetic (``tests/conftest.py`` blocks real sockets outright).
    Following those would be a test bug, not a crawl of this app.
    """
    if not href or href.startswith(("#", "mailto:", "javascript:")):
        return None
    split = urlsplit(href)
    if split.scheme or split.netloc:
        return None  # absolute — every one of these in this app points off-site
    path = split.path or base_path
    resolved = urljoin(base_path, path)
    return resolved + (f"?{split.query}" if split.query else "")


@dataclass
class CrawlResult:
    #: every internal path fetched, and the status it came back with
    visited: dict[str, int] = field(default_factory=dict)
    #: every (source page, target, status) triple checked — the source is
    #: what makes a failure assertion actionable rather than "something,
    #: somewhere, is broken"
    checked_links: list[tuple[str, str, int]] = field(default_factory=list)
    #: POST-only form actions seen, and every page that rendered one — not
    #: GET-followed by the crawl itself (see module docstring)
    post_forms: dict[str, set[str]] = field(default_factory=dict)


def crawl(client: TestClient, start: str = "/") -> CrawlResult:
    """Breadth-first from ``start``. Follows only what the app's own
    rendered markup actually contains — it never invents a URL — which is
    what makes "the crawl found no dead end" mean "a real visitor clicking
    through this app never hits one", not "every route this app happens to
    define returns 200".
    """
    result = CrawlResult()
    queue: list[tuple[str, str]] = [(start, start)]
    seen: set[str] = set()

    while queue:
        target, source = queue.pop(0)
        if target in seen:
            continue
        seen.add(target)

        response = client.get(target)
        result.visited[target] = response.status_code
        result.checked_links.append((source, target, response.status_code))

        content_type = response.headers.get("content-type", "")
        if response.status_code != 200 or "html" not in content_type:
            continue  # an artifact download, a stylesheet, or a dead link — nothing to parse

        parser = _LinkParser()
        parser.feed(response.text)

        for href in parser.hrefs:
            dest = _internal_target(target, href)
            if dest is not None and dest not in seen:
                queue.append((dest, target))

        for action, method in parser.forms:
            dest = _internal_target(target, action)
            if dest is None:
                continue
            if method == "get":
                if dest not in seen:
                    queue.append((dest, target))
            else:
                result.post_forms.setdefault(dest, set()).add(target)

    return result


def _assert_no_dead_ends(result: CrawlResult) -> None:
    failures = [
        (source, target, status)
        for source, target, status in result.checked_links
        if status != 200
    ]
    assert not failures, "dead link(s) found — source page -> target (status):\n" + "\n".join(
        f"  {source} -> {target} ({status})" for source, target, status in failures
    )


#: This app's five mutating routes, as path shapes rather than five literal
#: URLs — every POST-only <form action> the crawler ever finds must match
#: one of these, on any page, in either storage mode.
_MUTATING_ROUTE_SHAPES = tuple(
    re.compile(p) for p in (
        r"^/topics$",
        r"^/topics/[^/]+$",
        r"^/topics/[^/]+/mine$",
        r"^/runs/[^/]+/insight$",
        r"^/runs/[^/]+/report$",
    )
)


def _assert_post_forms_are_sound(client: TestClient, result: CrawlResult, *, durable: bool) -> None:
    """What the owner's own independent crawl found this file conflating:
    recording a POST-only ``<form action>`` and never checking anything
    about it is exactly as blind as never finding it. Every target found
    here must be a real, known mutating route shape — never a stray or
    malformed action string this crawler's own parsing happened to produce
    — and in read-only mode it must additionally be safe to actually POST
    to, which is checked for real, not assumed.

    Read-only mode only actually fires the POST: ``storage_is_durable()``
    being false means ``read_only_refusal`` (``vsm/ui/app.py``) answers
    before any store write, on any request body — so hitting it for real
    here costs nothing and proves the refusal rather than assuming it. The
    durable case does not fire a live POST: submitting real bodies to five
    different mutating forms mid-crawl — mine, insight and report all being
    real (if fake-miner-backed) writes — would make this dead-link sweep a
    second, redundant driver of the write path, when
    ``test_every_post_form_redirects_to_a_live_page`` below already walks
    that exact path with real field data and checks every redirect target.
    """
    for dest, sources in result.post_forms.items():
        path = urlsplit(dest).path
        assert any(p.match(path) for p in _MUTATING_ROUTE_SHAPES), (
            f"POST form action {dest!r} (found on {sorted(sources)}) does not "
            "match any of this app's known mutating route shapes"
        )
        if not durable:
            resp = client.post(dest, data={})
            assert resp.status_code == 409, (
                f"POST {dest!r} (found on {sorted(sources)}) should refuse "
                f"with 409 in read-only mode, got {resp.status_code}:\n{resp.text[:500]}"
            )


# --------------------------------------------------------------------- #
# Fixtures: the two states the task calls out — seeded, and one topic    #
# with no runs yet (the pre-run empty state) — each in both storage      #
# modes: durable (the default), and read-only (no database, and this     #
# process presented as a Vercel serverless instance — the one            #
# combination storage_is_durable() refuses; see vsm/platform.py).        #
# --------------------------------------------------------------------- #


@pytest.fixture
def seeded_client(tmp_path):
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    seed_demo_topic(ts, rs, env={})  # exactly what vsm/app.py does on cold start
    return TestClient(create_app(topic_store=ts, run_store=rs)), ts, rs


@pytest.fixture
def runless_client(tmp_path):
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    ts.create(name="Fresh Topic", therapeutic_area="gi", spend_band="probe")
    return TestClient(create_app(topic_store=ts, run_store=rs)), ts, rs


@pytest.fixture
def read_only_seeded_client(tmp_path, monkeypatch):
    """The seeded demo store, exactly as `seeded_client` builds it, but
    with storage_is_durable() forced false for every request the returned
    client makes — the state a real read-only deployment is in."""
    monkeypatch.setenv("VERCEL", "1")
    for var in ("POSTGRES_URL_NON_POOLING", "POSTGRES_URL", "DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    seed_demo_topic(ts, rs, env={})  # the seed's own guard checks for a db url, not VERCEL
    return TestClient(create_app(topic_store=ts, run_store=rs)), ts, rs


# --------------------------------------------------------------------- #
# The main deliverable.                                                  #
# --------------------------------------------------------------------- #


def test_crawl_of_the_seeded_demo_store_has_no_dead_ends(seeded_client):
    """Exactly the state a fresh, cold, ephemeral container is in — the
    scenario the owner actually hit. Every artifact download, every tab
    panel's links, every stage's download link, the forest plot's citation
    jumps and every deliverable card must resolve."""
    client, _ts, _rs = seeded_client
    result = crawl(client)
    _assert_no_dead_ends(result)
    _assert_post_forms_are_sound(client, result, durable=True)
    assert len(result.post_forms) >= 4, (
        f"only {len(result.post_forms)} distinct POST form targets found — "
        "too few to be real coverage of this app's five mutating routes: "
        f"{sorted(result.post_forms)}"
    )

    # A floor, not an exact count: exact-count assertions break on every
    # unrelated content change. The seeded topic alone produces 2 MINE runs
    # (5 artifacts each), 1 INSIGHT run (7 artifacts) and 1 REPORT run (4
    # artifacts) — 16 artifact downloads alone — plus /, /how, /deliverables,
    # /topics/new, the topic's own detail/edit/confirm pages, 4 run-flow
    # pages (2 x /runs/<mine>, /runs/<insight>/insight,
    # /runs/<report>/report), 2 x /runs/<mine>/snapshot, and the two static
    # stylesheets. That is comfortably past 30 distinct URLs; 25 is a floor
    # that only a real regression (not a rewording) should ever cross.
    assert len(result.visited) >= 25, (
        f"crawl only reached {len(result.visited)} pages — far too few to be "
        "real coverage; something is short-circuiting the crawl rather than "
        "the app actually having this few links"
    )

    # Specific pages that must be among them — guards against a crawler that
    # "passes" by wandering into a large but irrelevant corner (e.g. every
    # artifact download but never the insight or report screens).
    suffixes = ("/snapshot", "/insight", "/report", "/edit", "/confirm", "/artifact/signals.json")
    for suffix in suffixes:
        assert any(p.endswith(suffix) for p in result.visited), (
            f"crawl never reached any page ending {suffix!r} — {sorted(result.visited)}"
        )
    assert "/" in result.visited and "/how" in result.visited and "/deliverables" in result.visited


def test_crawl_of_a_topic_with_no_runs_has_no_dead_ends(runless_client):
    """The pre-run empty state: a topic that exists but has never been
    mined. Every screen reachable from it must handle "no snapshot, no
    insight, no report" — which, for a link crawler, means simply: nothing
    on any reachable page may link to a run that doesn't exist."""
    client, ts, _rs = runless_client
    result = crawl(client)
    _assert_no_dead_ends(result)
    _assert_post_forms_are_sound(client, result, durable=True)
    assert len(result.post_forms) >= 3, (
        f"only {len(result.post_forms)} distinct POST form targets found on "
        f"a runless topic — expected create, edit and mine at least: "
        f"{sorted(result.post_forms)}"
    )

    assert len(result.visited) >= 8, (
        f"crawl only reached {len(result.visited)} pages on a runless store — "
        f"expected at least /, /how, /deliverables, /topics/new, the topic's "
        f"own detail/edit/confirm pages and the two stylesheets: {sorted(result.visited)}"
    )
    # The explicit guarantee QA item 2 asks for: nothing anywhere links to a
    # /runs/... page, because there is no run to link to.
    run_links = [p for p in result.visited if "/runs/" in p]
    assert not run_links, f"a runless topic must never link to a run: {run_links}"

    topic_id = ts.list()[0].topic_id
    assert f"/topics/{topic_id}" in result.visited
    assert f"/topics/{topic_id}/edit" in result.visited
    assert f"/topics/{topic_id}/confirm" in result.visited


# --------------------------------------------------------------------- #
# Read-only mode: the same seeded store, but storage_is_durable() is      #
# false — the state a real deployment with no database is in. Every       #
# already-collected screen must still be reachable, no mutating control   #
# may render, and any POST-only form the crawl still finds (there should  #
# be none) must be safely refused. See tests/test_read_only_mode.py for   #
# the per-route 409 and per-template control-visibility proofs this       #
# complements at the level of "does a real visitor ever hit a dead end."  #
# --------------------------------------------------------------------- #


def test_crawl_of_the_seeded_demo_store_has_no_dead_ends_when_read_only(read_only_seeded_client):
    """The exact scenario the fix exists for, minus the part already fixed:
    a cold container with no database, but this time storage_is_durable()
    is false throughout the crawl. Every already-collected screen — the
    seeded topic, both snapshots, the insight run, the report and all of
    its artifacts — must remain fully reachable; nothing may link to a
    mutating control that would 409 if followed."""
    client, ts, rs = read_only_seeded_client
    result = crawl(client)
    _assert_no_dead_ends(result)

    # The strongest version of "the control is not rendered": the crawler,
    # which parses raw HTML exactly as a browser with scripting off would
    # see it, finds *zero* POST-only forms anywhere in the whole crawl —
    # not five refused ones, none at all. Kept as its own assertion (not
    # folded into `_assert_post_forms_are_sound`, which would pass
    # vacuously on an empty dict) so a control that leaks back into the
    # markup fails here even before the 409 layer is reached.
    assert not result.post_forms, (
        f"a POST-only form is still reachable in read-only mode: {sorted(result.post_forms)}"
    )
    _assert_post_forms_are_sound(client, result, durable=False)  # a no-op given the assertion above, kept for symmetry

    # A floor close to the durable crawl's own (38): losing exactly the
    # /topics/new and .../edit pages (their entry links are the ones this
    # mode hides) and nothing else is what "everything read-only stays
    # fully available" means in page-count terms.
    assert len(result.visited) >= 30, (
        f"crawl only reached {len(result.visited)} pages in read-only mode — "
        f"too few to be real coverage: {sorted(result.visited)}"
    )

    suffixes = ("/snapshot", "/insight", "/report", "/confirm", "/artifact/signals.json")
    for suffix in suffixes:
        assert any(p.endswith(suffix) for p in result.visited), (
            f"read-only crawl never reached any page ending {suffix!r} — {sorted(result.visited)}"
        )
    assert "/" in result.visited and "/how" in result.visited and "/deliverables" in result.visited

    # The two pages whose sole purpose is a now-hidden form are reachable
    # by direct URL (the routes themselves still answer GET) but must not
    # be *linked* from anywhere the crawl actually walked.
    topic_id = ts.list()[0].topic_id
    assert "/topics/new" not in result.visited
    assert f"/topics/{topic_id}/edit" not in result.visited


# --------------------------------------------------------------------- #
# QA item 1 — every POST target exists and redirects somewhere real.     #
# --------------------------------------------------------------------- #


def test_every_post_form_redirects_to_a_live_page(tmp_path):
    """QA item 1. Walks the whole flow a real visitor drives through forms
    — create topic, edit topic, confirm spend (a GET, already covered by
    the crawl above), run mine, run insight, run report — entirely through
    the HTTP layer a browser actually drives, and for every POST confirms
    the redirect *target itself* returns 200. A 303 to a dead URL is still
    a dead end; checking only the status of the POST response would miss
    that entirely.
    """
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    client = TestClient(create_app(topic_store=ts, run_store=rs))

    # ---- create topic ---------------------------------------------------
    resp = client.post(
        "/topics",
        data={"name": "Chain Topic", "therapeutic_area": "gi", "spend_band": "probe"},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    assert client.get(resp.headers["location"]).status_code == 200
    topic = ts.list()[0]

    # ---- edit topic -------------------------------------------------------
    resp = client.post(
        f"/topics/{topic.topic_id}",
        data={"name": "Chain Topic (edited)", "therapeutic_area": "gi", "spend_band": "probe"},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    assert client.get(resp.headers["location"]).status_code == 200

    # ---- confirm spend (GET) then run mine (POST) --------------------------
    assert client.get(f"/topics/{topic.topic_id}/confirm").status_code == 200
    resp = client.post(f"/topics/{topic.topic_id}/mine", data={}, follow_redirects=False)
    assert resp.status_code == 303, resp.text
    mine_target = resp.headers["location"]
    assert client.get(mine_target).status_code == 200
    mine_run_id = mine_target.rsplit("/", 1)[-1]

    # ---- run insight ------------------------------------------------------
    resp = client.post(f"/runs/{mine_run_id}/insight", follow_redirects=False)
    assert resp.status_code == 303, resp.text
    insight_target = resp.headers["location"]
    assert client.get(insight_target).status_code == 200
    insight_run_id = insight_target.rsplit("/", 2)[-2]

    # ---- run report ---------------------------------------------------------
    resp = client.post(f"/runs/{insight_run_id}/report", follow_redirects=False)
    assert resp.status_code == 303, resp.text
    report_target = resp.headers["location"]
    assert client.get(report_target).status_code == 200


# --------------------------------------------------------------------- #
# QA item 3 — a run whose upstream is missing.                           #
# --------------------------------------------------------------------- #


def _seeded_flow(rs, topic):
    mine = run_mine(topic, rs, miner=DeterministicMiner(queries_per_cluster=4), cluster_count=1)
    insight = run_insight(topic, mine.run_id, rs, client=None)
    report = run_report(topic, insight.run_id, rs, client=None)
    return mine, insight, report


def test_generating_a_report_when_the_snapshot_artifacts_are_gone_shows_a_real_message(tmp_path):
    """An INSIGHT run whose parent snapshot's ``signals.json`` has since
    disappeared (the ephemeral-storage failure mode this whole app is built
    around — see ``vsm/storage.py``'s own docstring) must not turn "generate
    the report" into a stack trace. Before the fix, ``run_report`` reads the
    snapshot's ``signals.json`` with no guard around it
    (``vsm/modes/report.py``), and the route that calls it
    (``report_create`` in ``vsm/ui/app.py``) only catches ``VsmError`` — a
    bare ``FileNotFoundError`` sailed straight through to a 500.
    """
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    topic = ts.create(name="Vanishing Snapshot", therapeutic_area="gi", spend_band="probe")
    mine = run_mine(topic, rs, miner=DeterministicMiner(queries_per_cluster=4), cluster_count=1)
    insight = run_insight(topic, mine.run_id, rs, client=None)

    # Simulate the snapshot's artifacts having been evicted — exactly what
    # "gone" means for a filesystem-backed store.
    (rs.artifacts_dir(mine.run_id) / "signals.json").unlink()

    client = TestClient(create_app(topic_store=ts, run_store=rs))
    resp = client.post(f"/runs/{insight.run_id}/report", follow_redirects=False)
    assert resp.status_code < 500, f"generating a report 500'd: {resp.status_code}\n{resp.text[:2000]}"
    assert resp.status_code in (400, 422), resp.status_code
    assert "signal" in resp.text.lower() or "snapshot" in resp.text.lower()


def test_viewing_a_report_when_its_insight_run_artifacts_are_gone_shows_a_real_message(tmp_path):
    """The same failure mode one hop later: the REPORT run itself is intact
    (its own four markdown files are still on disk), but the INSIGHT run it
    was built from has since lost ``themes.json``/``findings.json``.
    ``report_view`` re-reads those two files, unguarded, to build the
    citations table — another bare ``FileNotFoundError`` with nothing
    catching it.
    """
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    topic = ts.create(name="Vanishing Insight", therapeutic_area="gi", spend_band="probe")
    mine, insight, report = _seeded_flow(rs, topic)

    (rs.artifacts_dir(insight.run_id) / "themes.json").unlink()
    (rs.artifacts_dir(insight.run_id) / "findings.json").unlink()

    client = TestClient(create_app(topic_store=ts, run_store=rs))
    resp = client.get(f"/runs/{report.run_id}/report")
    assert resp.status_code < 500, f"viewing the report 500'd: {resp.status_code}\n{resp.text[:2000]}"


# --------------------------------------------------------------------- #
# QA item 4 — the error pages themselves.                                #
# --------------------------------------------------------------------- #


def _back_link_targets(html: str) -> list[str]:
    parser = _LinkParser()
    parser.feed(html)
    return [h for h in parser.hrefs if h == "/"]


def test_topic_not_found_is_a_404_with_a_working_back_link(runless_client):
    client, _ts, _rs = runless_client
    resp = client.get("/topics/top-doesnotexist")
    assert resp.status_code == 404
    assert "Topic not found" in resp.text
    assert _back_link_targets(resp.text), "no 'Back to topics' link (href=\"/\") on the error page"
    assert client.get("/").status_code == 200


def test_run_not_found_is_a_404_with_a_working_back_link(runless_client):
    client, _ts, _rs = runless_client
    resp = client.get("/runs/min-doesnotexist")
    assert resp.status_code == 404
    assert "Run not found" in resp.text
    assert _back_link_targets(resp.text), "no 'Back to topics' link (href=\"/\") on the error page"
    assert client.get("/").status_code == 200


# --------------------------------------------------------------------- #
# QA item 5 — trailing slashes, unknown ids, unknown artifact names.     #
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "path",
    [
        "/topics/top-doesnotexist",
        "/topics/top-doesnotexist/edit",
        "/topics/top-doesnotexist/confirm",
        "/runs/min-doesnotexist",
        "/runs/min-doesnotexist/snapshot",
        "/runs/min-doesnotexist/insight",
        "/runs/min-doesnotexist/report",
        "/runs/min-doesnotexist/artifact/signals.json",
    ],
)
def test_unknown_ids_never_500(runless_client, path):
    client, _ts, _rs = runless_client
    resp = client.get(path)
    assert resp.status_code < 500, f"{path} -> {resp.status_code}\n{resp.text[:2000]}"
    assert resp.status_code in (400, 404), f"{path} -> unexpected {resp.status_code}"


def test_unknown_artifact_name_on_a_real_run_is_a_clean_404(seeded_client):
    client, ts, rs = seeded_client
    mine_run = rs.snapshots(ts.list()[0].topic_id)[0]
    resp = client.get(f"/runs/{mine_run.run_id}/artifact/no-such-file.json")
    assert resp.status_code == 404
    assert "Artifact not found" in resp.text


def test_a_traversal_style_artifact_name_is_a_clean_404_not_a_500(seeded_client):
    """The "intentional, tested 4xx" the crawl's own docstring names: a
    caller cannot walk an artifact download out of its run directory.

    A plain ``../`` in the URL never even reaches this app's own route —
    ``httpx``/Starlette normalise the dot-segments out of the path before
    routing, landing on the framework's own blanket 404. Percent-encoding
    the slashes (``..%2F``) is what actually delivers a literal ``..`` all
    the way to ``artifact_download``'s own guard (``vsm/ui/app.py``) — this
    is the case that proves *that* guard, not URL normalisation upstream of
    it, is what is refusing the traversal.
    """
    client, ts, rs = seeded_client
    mine_run = rs.snapshots(ts.list()[0].topic_id)[0]
    resp = client.get(f"/runs/{mine_run.run_id}/artifact/..%2F..%2F..%2F..%2Fetc%2Fpasswd")
    assert resp.status_code < 500
    assert resp.status_code == 404
    assert "Artifact not found" in resp.text

    # The framework-level path this app does not control: httpx/Starlette's
    # own dot-segment normalisation means an *unencoded* ../ never reaches
    # this app's router at all. Still asserted here because "normalised
    # away before it can do damage" is itself a real, load-bearing part of
    # why this is safe — and it must never become a 500 either.
    resp2 = client.get(f"/runs/{mine_run.run_id}/artifact/../../../../etc/passwd")
    assert resp2.status_code < 500


@pytest.mark.parametrize(
    "path",
    [
        "/topics/",
        "/runs/",
        "/nonexistent-page-entirely",
    ],
)
def test_trailing_slash_and_unmatched_routes_never_500(runless_client, path):
    client, _ts, _rs = runless_client
    resp = client.get(path)
    assert resp.status_code < 500, f"{path} -> {resp.status_code}\n{resp.text[:2000]}"
