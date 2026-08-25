import pytest

from vsm.errors import BudgetExceeded
from vsm.guards.cost import SERP_USD, UNLOCKER_USD, CostCap, estimate_run_usd
from vsm.topics.model import band_for


def test_unlocker_is_twenty_times_a_serp_call():
    """The whole argument for querying the gold list first."""
    assert UNLOCKER_USD == pytest.approx(SERP_USD * 20)


def test_probe_costs_less_than_standard_costs_less_than_deep():
    totals = [
        estimate_run_usd(band_for(n), cluster_count=3).total_usd
        for n in ("probe", "standard", "deep")
    ]
    assert totals == sorted(totals) and len(set(totals)) == 3


def test_a_probe_buys_no_page_fetches_so_costs_nothing_for_them():
    est = estimate_run_usd(band_for("probe"), cluster_count=3)
    assert est.unlocker_usd == 0.0


def test_the_breakdown_names_every_line():
    est = estimate_run_usd(band_for("standard"), cluster_count=2)
    assert {line["item"] for line in est.breakdown} == {
        "serp", "discover", "unlocker", "model"
    }
    assert est.total_usd == pytest.approx(sum(line["usd"] for line in est.breakdown))


def test_the_cap_binds_and_reports_what_was_left():
    cap = CostCap(0.10)
    cap.spend(0.06)
    assert cap.remaining() == pytest.approx(0.04)
    with pytest.raises(BudgetExceeded, match="0.10"):
        cap.spend(0.09)


def test_spend_that_breaches_is_not_recorded():
    """A clean stop leaves the ledger truthful — we did not spend what we
    refused to spend."""
    cap = CostCap(0.10)
    cap.spend(0.06)
    with pytest.raises(BudgetExceeded):
        cap.spend(0.09)
    assert cap.spent() == pytest.approx(0.06)
