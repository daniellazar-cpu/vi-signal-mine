import pytest

from vsm.errors import GuardViolation
from vsm.guards.citations import bind_citations

LEDGER = {
    "sig-a": {"signal_id": "sig-a", "url": "https://gastro.org/x", "venue": "gastro.org",
              "captured_at": "2026-08-25T00:00:00+00:00", "collection_method": "serp_result"},
}


def test_a_bound_citation_comes_from_the_ledger_not_the_caller():
    got = bind_citations(["sig-a"], LEDGER)
    assert got[0].url == "https://gastro.org/x"
    assert got[0].venue_kind  # resolved from the registry, not passed in


def test_an_unknown_id_blocks_rather_than_being_dropped():
    """Dropping it would turn a fabricated citation into a silently
    uncited claim, which is the same lie with fewer symptoms."""
    with pytest.raises(GuardViolation, match="G1"):
        bind_citations(["sig-a", "sig-invented"], LEDGER)


def test_an_empty_citation_list_blocks():
    with pytest.raises(GuardViolation, match="no signal ids"):
        bind_citations([], LEDGER)


def test_the_error_names_the_offending_ids():
    with pytest.raises(GuardViolation, match="sig-invented"):
        bind_citations(["sig-invented"], LEDGER)
