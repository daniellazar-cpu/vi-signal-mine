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


def test_g6_blocks_an_uncorroborated_finding_in_the_body():
    weak = Finding("f1", "x", ("a",), 1, "single_source")
    with pytest.raises(GuardViolation, match="single_source"):
        assert_body_is_corroborated([weak])


def test_g6_passes_a_corroborated_body():
    ok = Finding("f1", "x", ("a", "b", "c"), 3, "corroborated")
    assert_body_is_corroborated([ok]) is None
