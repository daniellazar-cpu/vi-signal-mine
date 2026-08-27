"""The dashboard: what it ranks, and what it says when it can say nothing.

The app had no overview. Everything a person opens the tool to find out — what
moved, where the two audiences disagree, what has become sayable — lived inside
one snapshot's page, three clicks in and for one topic at a time.

The empty states carry as much weight as the rows here. A panel that cannot say
*why* it is empty guesses, and on the deployment it guessed wrong: "needs a
topic swept twice" on a store that had been swept twice and simply had nothing
moving. Those are different facts and only one is an instruction.
"""

from __future__ import annotations

import pytest

from vsm.ui.overview import MOVED_MIN_PCT, build_overview, latest_insight_per_topic


@pytest.fixture
def client_factory(tmp_path, monkeypatch):
    """A real client over a real store, with the momentum artifact supplied."""
    from fastapi.testclient import TestClient

    from vsm.runs.store import RunStore
    from vsm.topics.store import TopicStore
    from vsm.ui.app import create_app

    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    monkeypatch.delenv("VSM_ACCESS_KEY", raising=False)
    made = {"n": 0}

    def make(*, momentum):
        made["n"] += 1
        root = tmp_path / f"s{made['n']}"
        root.mkdir(parents=True, exist_ok=True)
        ts = TopicStore(root / "db")
        rs = RunStore(root / "db", root / "var")
        t = ts.create(name="Brand A", therapeutic_area="", spend_band="probe")
        for _ in range(2):
            m = rs.start(t.topic_id, "mine"); rs.finish(m.run_id, "complete", 0.0)
        i = rs.start(t.topic_id, "insight"); rs.finish(i.run_id, "complete", 0.0)
        rs.write_artifact(i.run_id, "momentum.json", momentum)
        return TestClient(create_app(topic_store=ts, run_store=rs))

    return make


class _Run:
    def __init__(self, run_id, topic_id, mode, status="complete", cost=0.0):
        self.run_id, self.topic_id, self.mode = run_id, topic_id, mode
        self.status, self.cost_usd = status, cost
        self.parent_run_id = None


class _Topic:
    def __init__(self, topic_id, name):
        self.topic_id, self.name = topic_id, name


def _reader(store):
    def read(run_id, name):
        try:
            return store[(run_id, name)]
        except KeyError:
            raise FileNotFoundError(name)
    return read


# ------------------------------------------------------------------- ranking --

def test_moved_is_ranked_by_absolute_change_not_direction():
    """A theme collapsing is as much news as one spiking."""
    topics = [_Topic("t1", "Brand A")]
    runs = {"t1": [_Run("m1", "t1", "mine"), _Run("i1", "t1", "insight")]}
    store = {("i1", "momentum.json"): [
        {"theme_name": "up a bit", "volume_prior": 10, "volume_now": 12, "delta": 2, "delta_pct": 20.0},
        {"theme_name": "down a lot", "volume_prior": 10, "volume_now": 2, "delta": -8, "delta_pct": -80.0},
        {"theme_name": "up a lot", "volume_prior": 10, "volume_now": 15, "delta": 5, "delta_pct": 50.0},
    ]}
    ov = build_overview(topics, runs, _reader(store))
    assert [r["theme"] for r in ov["moved"]] == ["down a lot", "up a lot", "up a bit"]


def test_a_theme_with_no_prior_snapshot_is_not_reported_as_flat():
    """Rendering it at 0% would claim it was measured and did not move."""
    topics = [_Topic("t1", "Brand A")]
    runs = {"t1": [_Run("i1", "t1", "insight")]}
    store = {("i1", "momentum.json"): [
        {"theme_name": "first time", "volume_prior": None, "volume_now": 9,
         "delta": None, "delta_pct": None},
    ]}
    ov = build_overview(topics, runs, _reader(store))
    assert ov["moved"] == []
    assert ov["moved_comparable"] == 0


def test_churn_below_the_threshold_is_not_reported_as_movement():
    """Every sweep re-queries a live web. A panel full of ±3% wobble teaches
    people to ignore the panel, which costs more than showing nothing."""
    topics = [_Topic("t1", "Brand A")]
    runs = {"t1": [_Run("i1", "t1", "insight")]}
    store = {("i1", "momentum.json"): [
        {"theme_name": "noise", "volume_prior": 100, "volume_now": 103, "delta": 3, "delta_pct": 3.0},
    ]}
    ov = build_overview(topics, runs, _reader(store))
    assert ov["moved"] == []
    assert ov["moved_comparable"] == 1, "it was compared, it just did not move"


def test_the_empty_moved_panel_distinguishes_no_baseline_from_no_movement(client_factory):
    """The bug this caught on the deployment. Two snapshots, nothing moving, and
    the panel told the reader to sweep twice — which they already had."""
    c = client_factory(momentum=[
        {"theme_name": "flat", "volume_prior": 10, "volume_now": 10, "delta": 0, "delta_pct": 0.0}])
    body = c.get("/").text
    assert "none moved more than" in body
    assert "swept twice" not in body

    c2 = client_factory(momentum=[
        {"theme_name": "new", "volume_prior": None, "volume_now": 4,
         "delta": None, "delta_pct": None}])
    body2 = c2.get("/").text
    assert "swept twice" in body2


def test_a_theme_only_one_side_discussed_is_counted_never_shown_as_zero():
    """Silence is not agreement — the product's own rule."""
    topics = [_Topic("t1", "Brand A")]
    runs = {"t1": [_Run("i1", "t1", "insight")]}
    store = {("i1", "duallens.json"): [
        {"theme_name": "one-sided", "divergence": None, "hcp_net": 0.4, "patient_net": None},
        {"theme_name": "both", "divergence": -1.2, "hcp_net": 0.4, "patient_net": -0.8},
    ]}
    ov = build_overview(topics, runs, _reader(store))
    assert [r["theme"] for r in ov["divergence"]] == ["both"]
    assert ov["not_comparable"] == 1


def test_only_corroborated_findings_are_called_safe_to_say():
    topics = [_Topic("t1", "Brand A")]
    runs = {"t1": [_Run("i1", "t1", "insight")]}
    store = {("i1", "findings.json"): [
        {"statement": "solid", "tier": "corroborated", "independent_sources": 5},
        {"statement": "thin", "tier": "emerging", "independent_sources": 2},
    ]}
    ov = build_overview(topics, runs, _reader(store))
    assert [r["statement"] for r in ov["sayable"]] == ["solid"]
    assert ov["emerging"] == 1


def test_only_the_latest_insight_run_counts():
    """An older run's momentum figure describes a comparison that has since been
    superseded, and one topic's history must not crowd out other topics."""
    topics = [_Topic("t1", "Brand A")]
    runs = {"t1": [_Run("i1", "t1", "insight"), _Run("i2", "t1", "insight")]}
    assert latest_insight_per_topic(runs)["t1"].run_id == "i2"
    store = {
        ("i1", "findings.json"): [{"statement": "old", "tier": "corroborated", "independent_sources": 9}],
        ("i2", "findings.json"): [{"statement": "new", "tier": "corroborated", "independent_sources": 3}],
    }
    ov = build_overview(topics, runs, _reader(store))
    assert [r["statement"] for r in ov["sayable"]] == ["new"]


def test_an_incomplete_insight_run_is_ignored():
    topics = [_Topic("t1", "Brand A")]
    runs = {"t1": [_Run("i1", "t1", "insight", status="running")]}
    assert latest_insight_per_topic(runs) == {}


# ----------------------------------------------------------------- attention --

@pytest.mark.parametrize("modes,expected", [
    ([], "never run"),
    ([("mine", "complete")], "collected, not analysed"),
    ([("mine", "complete"), ("mine", "complete"), ("insight", "complete")], None),
    ([("mine", "stopped_on_budget")], "stopped on budget"),
    ([("mine", "failed")], "last run failed"),
])
def test_attention_names_the_state_and_offers_one_action(modes, expected):
    topics = [_Topic("t1", "Brand A")]
    runs = {"t1": [_Run(f"r{i}", "t1", m, s) for i, (m, s) in enumerate(modes)]}
    ov = build_overview(topics, runs, _reader({}))
    if expected is None:
        assert ov["attention"] == [], ov["attention"]
    else:
        assert len(ov["attention"]) == 1
        row = ov["attention"][0]
        assert row["why"] == expected
        assert row["action"] and row["href"], "a state with no next step is a complaint"


def test_a_broken_artifact_does_not_take_the_whole_dashboard_down():
    """This screen aggregates across every topic, so one unreadable run must not
    cost a person the view of all the others."""
    topics = [_Topic("t1", "Brand A"), _Topic("t2", "Brand B")]
    runs = {"t1": [_Run("i1", "t1", "insight")], "t2": [_Run("i2", "t2", "insight")]}

    def read(run_id, name):
        if run_id == "i1":
            raise ValueError("corrupt")
        if (run_id, name) == ("i2", "findings.json"):
            return [{"statement": "fine", "tier": "corroborated", "independent_sources": 4}]
        raise FileNotFoundError(name)

    ov = build_overview(topics, runs, read)
    assert [r["statement"] for r in ov["sayable"]] == ["fine"]


def test_every_panel_reports_its_own_total():
    """A panel showing six of forty and saying only "six" is silent truncation
    in a different costume."""
    topics = [_Topic("t1", "Brand A")]
    runs = {"t1": [_Run("i1", "t1", "insight")]}
    store = {("i1", "findings.json"): [
        {"statement": f"f{i}", "tier": "corroborated", "independent_sources": 3 + i}
        for i in range(20)]}
    ov = build_overview(topics, runs, _reader(store), panel_rows=6)
    assert len(ov["sayable"]) == 6
    assert ov["sayable_total"] == 20


def test_the_threshold_is_stated_not_hidden():
    """The number the panel filters on has to be visible, or "nothing moved" is
    unfalsifiable."""
    topics = [_Topic("t1", "A")]
    ov = build_overview(topics, {"t1": []}, _reader({}))
    assert ov["moved_threshold"] == MOVED_MIN_PCT
