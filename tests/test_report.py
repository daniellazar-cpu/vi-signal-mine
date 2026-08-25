import pytest

from vsm.errors import GuardViolation
from vsm.modes.insight import run_insight
from vsm.modes.report import run_report
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore

ARTIFACTS = ("pulse_report.md", "provenance_appendix.md", "methodology.md",
             "worth_considering.md")


@pytest.fixture
def env(tmp_path):
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    topic = ts.create(name="OIC", therapeutic_area="gastroenterology",
                      spend_band="standard", brand="Symproic", molecule="naldemedine")
    return ts, rs, topic


def _rows(n, venue="studentdoctor.net", theme="tolerability"):
    return [{"signal_id": f"s{i}", "venue": f"v{i}.example.org", "theme": theme,
             "title": f"{theme} {i}", "excerpt": theme,
             "captured_at": "2026-08-25T00:00:00+00:00",
             "collection_method": "serp_result",
             "url": f"https://v{i}.example.org/{i}"} for i in range(n)]


def _pipeline(rs, topic, rows):
    mine = rs.start(topic.topic_id, "mine")
    rs.write_artifact(mine.run_id, "signals.json", rows)
    rs.finish(mine.run_id, "complete", cost_usd=0.01)
    return run_insight(topic, mine.run_id, rs)


def test_report_writes_its_four_artifacts(env):
    ts, rs, topic = env
    insight = _pipeline(rs, topic, _rows(4))
    run = run_report(topic, insight.run_id, rs)
    for name in ARTIFACTS:
        assert (rs.artifacts_dir(run.run_id) / name).exists(), name


def test_the_methodology_states_the_author_basis(env):
    ts, rs, topic = env
    insight = _pipeline(rs, topic, _rows(4))
    run = run_report(topic, insight.run_id, rs)
    text = rs.read_artifact(run.run_id, "methodology.md")
    assert "venue" in text.lower()


def test_the_methodology_states_the_ae_scope_limit_exactly_once(env):
    """Spec D10 + the no-over-disclosure rule: say it once, in the appendix
    where scope statements belong, and nowhere else."""
    ts, rs, topic = env
    insight = _pipeline(rs, topic, _rows(4))
    run = run_report(topic, insight.run_id, rs)
    method = rs.read_artifact(run.run_id, "methodology.md").lower()
    pulse = rs.read_artifact(run.run_id, "pulse_report.md").lower()
    assert method.count("adverse event") == 1
    assert "adverse event" not in pulse


def test_the_provenance_appendix_lists_every_cited_signal(env):
    ts, rs, topic = env
    rows = _rows(4)
    insight = _pipeline(rs, topic, rows)
    run = run_report(topic, insight.run_id, rs)
    appendix = rs.read_artifact(run.run_id, "provenance_appendix.md")
    for row in rows:
        assert row["signal_id"] in appendix
        assert row["url"] in appendix


def test_an_uncorroborated_finding_cannot_reach_the_body(env):
    """G6, end to end. One signal is an anecdote."""
    ts, rs, topic = env
    insight = _pipeline(rs, topic, _rows(1))
    run = run_report(topic, insight.run_id, rs)
    body = rs.read_artifact(run.run_id, "pulse_report.md")
    assert "single source" in body.lower() or "not corroborated" in body.lower()


def test_forecast_language_from_the_model_blocks_the_report(env):
    """G5 fires on model output exactly as on our own prose."""
    ts, rs, topic = env
    insight = _pipeline(rs, topic, _rows(4))

    class _Client:
        def complete_structured(self, **kw):
            class _Out:
                ok = True
                data = {"sections": [{"heading": "Outlook",
                                      "body": "Discussion will grow through Q4.",
                                      "signal_ids": ["s0", "s1", "s2"]}],
                        "considerations": []}
                reason = ""
            return _Out()

    with pytest.raises(GuardViolation, match="G5"):
        run_report(topic, insight.run_id, rs, client=_Client())


def test_a_fabricated_signal_id_blocks_the_report(env):
    """G1 end to end."""
    ts, rs, topic = env
    insight = _pipeline(rs, topic, _rows(4))

    class _Client:
        def complete_structured(self, **kw):
            class _Out:
                ok = True
                data = {"sections": [{"heading": "Themes", "body": "Tolerability dominates.",
                                      "signal_ids": ["s0", "sig-invented"]}],
                        "considerations": []}
                reason = ""
            return _Out()

    with pytest.raises(GuardViolation, match="G1"):
        run_report(topic, insight.run_id, rs, client=_Client())


def test_a_never_say_term_blocks_the_report(env):
    """G4 end to end."""
    ts, rs, topic = env
    topic = ts.update(topic.topic_id, never_say=("Symproic",))
    insight = _pipeline(rs, topic, _rows(4))

    class _Client:
        def complete_structured(self, **kw):
            class _Out:
                ok = True
                data = {"sections": [{"heading": "Themes",
                                      "body": "Symproic dominates the discussion.",
                                      "signal_ids": ["s0", "s1", "s2"]}],
                        "considerations": []}
                reason = ""
            return _Out()

    with pytest.raises(GuardViolation, match="G4"):
        run_report(topic, insight.run_id, rs, client=_Client())
