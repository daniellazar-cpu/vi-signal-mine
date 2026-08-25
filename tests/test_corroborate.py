import pytest

from vsm.analysis.corroborate import (
    Finding, corroborate, independent_source_count, tier_for_count,
)
from vsm.errors import GuardViolation
from vsm.guards.corroboration import assert_body_is_corroborated


def sig(sid, venue, title):
    return {"signal_id": sid, "venue": venue, "title": title,
            "url": f"https://{venue}/{sid}"}


def test_three_distinct_domains_are_three_sources():
    rows = [sig("a", "gastro.org", "AGA updates OIC guidance"),
            sig("b", "reddit.com", "anyone using naldemedine?"),
            sig("c", "medscape.com", "OIC management review")]
    assert independent_source_count(rows) == 3


def test_subdomains_of_one_host_are_one_source():
    rows = [sig("a", "op-med.doximity.com", "one"), sig("b", "www.doximity.com", "two")]
    assert independent_source_count(rows) == 1


def test_five_syndicated_copies_of_one_release_count_once():
    """The case that would otherwise manufacture confidence out of a single PR."""
    title = "Company announces positive topline results"
    rows = [sig(str(i), f"outlet{i}.com", title) for i in range(5)]
    assert independent_source_count(rows) == 1


def test_syndication_plus_one_genuine_source_is_two():
    title = "Company announces positive topline results"
    rows = [sig(str(i), f"outlet{i}.com", title) for i in range(4)]
    rows.append(sig("real", "reddit.com", "what do people make of this?"))
    assert independent_source_count(rows) == 2


def test_titles_differing_only_in_case_and_space_are_the_same():
    rows = [sig("a", "x.com", "OIC Guidance  Updated"),
            sig("b", "y.com", "oic guidance updated")]
    assert independent_source_count(rows) == 1


def test_empty_titles_do_not_merge_into_one_source():
    """Without excluding the empty title from the index, three signals with
    no title at all would all link on "" and collapse to a single source —
    undercounting three genuinely independent outlets down to single_source,
    which would silently keep a corroborated finding out of the report."""
    rows = [sig("a", "gastro.org", ""), sig("b", "reddit.com", ""),
            sig("c", "medscape.com", "")]
    assert independent_source_count(rows) == 3


def test_the_three_tiers():
    assert tier_for_count(3) == "corroborated"
    assert tier_for_count(5) == "corroborated"
    assert tier_for_count(2) == "emerging"
    assert tier_for_count(1) == "single_source"
    assert tier_for_count(0) == "single_source"


def test_corroborate_assembles_findings_with_their_tier():
    by_id = {r["signal_id"]: r for r in [
        sig("a", "gastro.org", "one"), sig("b", "reddit.com", "two"),
        sig("c", "medscape.com", "three"), sig("d", "gastro.org", "four"),
    ]}
    findings = corroborate(
        [{"statement": "Tolerability is the dominant concern",
          "signal_ids": ["a", "b", "c"]},
         {"statement": "Cost comes up occasionally", "signal_ids": ["d"]}],
        by_id,
    )
    assert findings[0].tier == "corroborated"
    assert findings[0].independent_sources == 3
    # Pinned to the actual carried-through fields, not just the tier, so a
    # findings-assembler that drops or reorders signal_ids still fails here.
    assert findings[0].signal_ids == ("a", "b", "c")
    assert findings[1].tier == "single_source"
    assert findings[1].independent_sources == 1
    assert findings[1].signal_ids == ("d",)


def test_corroborate_excludes_a_hallucinated_id_from_signal_ids():
    """independent_sources and signal_ids must agree. Before this, a claim
    citing an id absent from the ledger would compute the count off the
    resolved rows but still list every id it was given — so a finding could
    say independent_sources=3 while carrying four ids, one of which resolves
    to nothing. A downstream guard binds every id in signal_ids back to a
    real row and blocks the whole report if one fails; a phantom id left in
    the list would let one hallucination sink a report built on three good
    sources."""
    by_id = {r["signal_id"]: r for r in [
        sig("a", "gastro.org", "one"), sig("b", "reddit.com", "two"),
        sig("c", "medscape.com", "three"),
    ]}
    findings = corroborate(
        [{"statement": "x", "signal_ids": ["a", "b", "c", "does-not-exist"]}],
        by_id,
    )
    finding = findings[0]
    assert finding.signal_ids == ("a", "b", "c")
    assert finding.independent_sources == 3
    assert len(finding.signal_ids) == finding.independent_sources


def test_corroborate_records_a_hallucinated_id_rather_than_erasing_it():
    """Dropping the id silently would hide that the model invented a
    citation; recording it in unresolved_ids does neither — it is visible
    afterwards without corrupting signal_ids or independent_sources."""
    by_id = {r["signal_id"]: r for r in [sig("a", "gastro.org", "one")]}
    findings = corroborate(
        [{"statement": "x", "signal_ids": ["a", "does-not-exist"]}],
        by_id,
    )
    assert findings[0].signal_ids == ("a",)
    assert findings[0].unresolved_ids == ("does-not-exist",)


def test_duplicate_signal_ids_are_deduplicated_preserving_order():
    """A repeated id must count once in signal_ids, in first-seen order —
    not the effect on independent_sources (union-find already collapses a
    sid unioned with itself), but signal_ids itself must not overstate the
    evidence a finding rests on."""
    by_id = {r["signal_id"]: r for r in [
        sig("a", "gastro.org", "one"), sig("b", "reddit.com", "two"),
    ]}
    findings = corroborate(
        [{"statement": "x", "signal_ids": ["b", "a", "b", "a"]}],
        by_id,
    )
    assert findings[0].signal_ids == ("b", "a")


def test_g6_blocks_an_uncorroborated_finding_in_the_body():
    weak = Finding("f1", "x", ("a",), 1, "single_source")
    with pytest.raises(GuardViolation, match="single_source"):
        assert_body_is_corroborated([weak])


def test_g6_blocks_an_emerging_finding_in_the_body():
    """Only 'corroborated' may reach the report body. 'emerging' is real —
    two independent sources is a provisional finding, not nothing — but it
    belongs in a separately labelled section, not the body this guard
    protects."""
    emerging = Finding("f1", "x", ("a", "b"), 2, "emerging")
    with pytest.raises(GuardViolation, match="emerging"):
        assert_body_is_corroborated([emerging])


def test_g6_passes_a_corroborated_body():
    ok = Finding("f1", "x", ("a", "b", "c"), 3, "corroborated")
    assert_body_is_corroborated([ok]) is None
