import pytest

from vsm.errors import BudgetExceeded
from vsm.guards.cost import CostCap, estimate_run_usd
from vsm.mining.budget import (
    DISCOVER_COST_PER_RESULT_USD,
    SERP_COST_PER_REQUEST_USD,
    UNLOCKER_COST_PER_SUCCESS_USD,
)
from vsm.topics.model import band_for


def test_the_estimate_is_priced_from_the_one_set_of_bright_data_prices():
    """The interstitial and the ledger must quote the same run.

    They once did not: ``guards/cost.py`` carried its own $0.03 Unlocker literal
    against ``mining/budget.py``'s $0.003 — a 10x disagreement about what a run
    costs, shown to an operator who was being asked to approve the spend. The
    prices below are the PRD §13.1 verified figures ($1.50/1,000 SERP,
    ~$3/1,000 successful Unlocker, $1.80 per ~600 parsed Discover results); the
    arithmetic asserts the estimator reads them rather than re-declaring them.
    """
    assert SERP_COST_PER_REQUEST_USD == 0.0015
    assert UNLOCKER_COST_PER_SUCCESS_USD == 0.003
    assert DISCOVER_COST_PER_RESULT_USD == 0.003
    assert UNLOCKER_COST_PER_SUCCESS_USD == pytest.approx(SERP_COST_PER_REQUEST_USD * 2)

    band, clusters = band_for("deep"), 3
    est = estimate_run_usd(band, cluster_count=clusters)
    assert est.serp_usd == pytest.approx(
        band.queries_per_cluster * clusters * SERP_COST_PER_REQUEST_USD
    )
    assert est.discover_usd == pytest.approx(
        band.discover_results_per_cluster * clusters * DISCOVER_COST_PER_RESULT_USD
    )
    assert est.unlocker_usd == pytest.approx(
        band.page_fetches_per_cluster * clusters * UNLOCKER_COST_PER_SUCCESS_USD
    )


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
