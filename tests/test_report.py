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


def _rows(n, theme="tolerability"):
    """``n`` signals on ``n`` genuinely distinct publishers.

    Each row lives on its own registrable domain (``outlet0.com``,
    ``outlet1.com``, ...), none of which is in the gold-list registry, so
    each one is its own independent source under the publisher-domain path
    in ``independence_key`` — unlike four subdomains of one registrable
    domain (the earlier ``v{i}.example.org`` shape), which all collapse to
    a single source and can never produce a ``corroborated`` finding. That
    collapse previously meant no test in this file ever exercised the
    corroborated-claim path in the report body; see
    ``test_a_corroborated_finding_reaches_the_report_body``.
    """
    return [{"signal_id": f"s{i}", "venue": f"outlet{i}.com", "theme": theme,
             "title": f"{theme} {i}", "excerpt": theme,
             "captured_at": "2026-08-25T00:00:00+00:00",
             "collection_method": "serp_result",
             "url": f"https://outlet{i}.com/{i}"} for i in range(n)]


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
    """A bare 'venue' substring is too weak to pin this: the 'Where' section
    also says 'venue registry' for an unrelated reason, so that check would
    still pass even if the author-class basis statement were deleted
    outright. Assert the actual claim instead."""
    ts, rs, topic = env
    insight = _pipeline(rs, topic, _rows(4))
    run = run_report(topic, insight.run_id, rs)
    text = rs.read_artifact(run.run_id, "methodology.md").lower()
    assert "author class" in text
    assert "derived from the venue" in text


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
    # Asserted as the property rather than by the word "single source", which
    # the vocabulary pass removed: the tier column and the source count said the
    # same thing, and only one of them needed a glossary. What G6 actually
    # forbids is a *claim sentence* about a one-source theme, so that is what
    # this checks — the theme still appears in the counts table.
    assert "| 1 |" in body, "the theme lost its row in the counts table"
    claims = body.split("## Backed by 3 or more sources")
    if len(claims) > 1:
        section = claims[1].split("##")[0]
        assert "independent sources," not in section, (
            "a one-source theme earned a claim sentence"
        )


def test_a_corroborated_finding_reaches_the_report_body(env):
    """G6, the other direction. Four genuinely independent publishers clear
    the three-source bar, and the resulting claim — not just a count in the
    themes table, but the actual assertion about the theme — must reach the
    main body with its source count visible. If that section were
    broken (e.g. never populated), the fallback text says no theme has
    reached three sources yet, which does not contain this phrase."""
    ts, rs, topic = env
    insight = _pipeline(rs, topic, _rows(4))
    run = run_report(topic, insight.run_id, rs)
    body = rs.read_artifact(run.run_id, "pulse_report.md")
    # The claim now states the count instead of naming a category: "wtf is
    # Corroborated" was the owner's reaction to meeting the old word.
    assert "4 independent sources" in body.lower()
    corroborated_section = body.split("## Backed by 3 or more sources")[1].split("## Backed by 2")[0]
    assert "tolerability" in corroborated_section.lower()


def test_an_emerging_finding_appears_only_under_its_own_heading(env):
    """Two independent sources is real but provisional (spec: 'emerging' is
    publishable, but only in a section that names the tier). It must not
    sit in the main 'Corroborated findings' section, which this snapshot's
    theme has not earned."""
    ts, rs, topic = env
    insight = _pipeline(rs, topic, _rows(2))
    run = run_report(topic, insight.run_id, rs)
    body = rs.read_artifact(run.run_id, "pulse_report.md")

    corroborated_section = body.split("## Backed by 3 or more sources")[1].split("## Backed by 2")[0]
    emerging_section = body.split("## Backed by 2 sources")[1].split("## What changed")[0]

    assert "tolerability" not in corroborated_section.lower()
    assert "tolerability" in emerging_section.lower()
    # The section states the count and what it licenses, rather than naming
    # a category the reader would have to look up.
    assert "2 independent sources" in emerging_section
    assert "attribute it" in emerging_section


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
