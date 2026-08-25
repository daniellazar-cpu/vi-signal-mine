"""MINE — one dated snapshot of a topic.

Order of operations, and why:

1. **Lexicon.** The model turns the topic into clusters and query strings. It
   contributes *strings only* — gold routing, ``site:`` scoping, band widths and
   the recency split all stay deterministic, which is what makes an offline dry
   run rehearse the live sweep query-for-query.
2. **Estimate, then cap.** The estimate is computed before a single call, and
   the cap is checked against it. A cap that binds after the spend is not a cap.
3. **Sweep.** Gold-scoped SERP first, Discover per cluster, open web only as a
   tail if the gold list under-delivers, page fetches last and fewest.
4. **Stamp and write.** Every row carries ``topic_id`` and ``snapshot_at`` so it
   can be placed in a series.

A cap breach ends the run at ``stopped_on_budget`` with whatever rows exist. It
does not raise past this function: overspending is the failure, stopping is not.
"""

from __future__ import annotations

from typing import Any

from vsm.errors import BudgetExceeded
from vsm.guards.cost import CostCap, estimate_run_usd
from vsm.llm.prompts import LEXICON_SYSTEM
from vsm.llm.schema import LEXICON_SCHEMA
from vsm.mining.miner import MiningConfig
from vsm.runs.model import Run
from vsm.runs.store import RunStore
from vsm.topics.model import SpendBand, Topic

__all__ = ["run_mine", "build_clusters", "config_for"]


def config_for(band: SpendBand) -> MiningConfig:
    """A spend band → the vendored miner's config.

    Handed to ``LiveSignalMining(config=...)`` at construction. It is not a
    ``run()`` argument — the parent's ``run()`` takes only ``campaign_id``,
    ``clusters`` and an optional per-cluster query override.
    """
    return MiningConfig(
        queries_per_cluster=band.queries_per_cluster,
        serp_results_per_query=band.serp_results_per_query,
        discover_results_per_cluster=band.discover_results_per_cluster,
        page_fetches_per_cluster=band.page_fetches_per_cluster,
        fetch_pages=band.page_fetches_per_cluster > 0,
    )


def build_clusters(topic: Topic, client: Any | None) -> list[dict[str, Any]]:
    """Topic → clusters. Falls back to a deterministic single cluster offline.

    The fallback is not a degraded model call; it is the honest offline shape,
    and it is what ``VSM_MINER=fake`` demonstrations run on.
    """
    if client is None:
        terms = [t for t in (topic.brand, topic.molecule, *topic.competitors) if t]
        return [
            {
                "cluster_id": "c1",
                "label": topic.name,
                "terms": terms or [topic.name],
                "areas": [topic.therapeutic_area],
            }
        ]
    user = (
        f"Topic: {topic.name}\n"
        f"Therapeutic area: {topic.therapeutic_area}\n"
        f"Brand: {topic.brand or '(none)'}\n"
        f"Molecule (INN): {topic.molecule or '(none)'}\n"
        f"Competitors: {', '.join(topic.competitors) or '(none)'}\n"
        f"Questions we care about:\n"
        + "\n".join(f"- {q}" for q in topic.questions)
    )
    out = client.complete_structured(
        system=LEXICON_SYSTEM, user=user, schema=LEXICON_SCHEMA, max_output_tokens=2048
    )
    if not out.ok or not out.data:
        raise RuntimeError(f"lexicon pass failed: {out.reason}")
    return list(out.data.get("clusters", []))


def run_mine(
    topic: Topic,
    store: RunStore,
    *,
    client: Any | None = None,
    miner: Any | None = None,
    cluster_count: int | None = None,
    cap_usd: float | None = None,
) -> Run:
    band = topic.band()
    run = store.start(topic.topic_id, "mine")
    cap = CostCap(cap_usd if cap_usd is not None else 5.0)

    # Read the model's cumulative spend directly as `client.spend.usd` — never
    # through `getattr(client, "spend", default)`. A zero produced by a
    # renamed attribute is indistinguishable from a run that genuinely spent
    # nothing. But `client.spend` is the client's *lifetime* ledger, not this
    # run's — one `AnthropicClient` shared across two MINEs, or an INSIGHT
    # run after a MINE, would otherwise bill the earlier call's cost to this
    # run's cap and report it as this run's spend. Snapshot before the call
    # and charge only the delta.
    spend_before_lexicon = client.spend.usd if client is not None else 0.0
    clusters = build_clusters(topic, client)

    # MiningConfig is CONSTRUCTOR state on LiveSignalMining, not a run()
    # argument. A caller that wants a configured live miner builds it with
    # `LiveSignalMining(serp=..., config=config_for(band))` and passes it in;
    # `run_mine` only decides the shape, so a test can inject a fake.
    stopped, reason, outcome = False, "", None

    # There is a genuine chicken-and-egg here: the estimate needs a cluster
    # count, and the cluster count comes from the lexicon call, so that call
    # has already happened — and already been billed — by the time we get
    # here. The fix is not to reorder around it (there is no way to know the
    # cluster count before making it) but to account for it: charge the real
    # lexicon spend to the run's cap immediately, before the estimate check,
    # so the cap governs the run's whole spend and not only the part that
    # comes after the lexicon call.
    lexicon_usd = (
        round(client.spend.usd - spend_before_lexicon, 6) if client is not None else 0.0
    )
    if client is not None:
        try:
            cap.spend(lexicon_usd)
        except BudgetExceeded as exc:
            stopped = True
            reason = f"the lexicon call alone breached the cap: {exc}"

    n = cluster_count if cluster_count is not None else len(clusters)
    estimate = estimate_run_usd(band, cluster_count=n)

    if not stopped:
        try:
            cap.spend(estimate.total_usd)
        except BudgetExceeded as exc:
            stopped, reason = True, str(exc)

    # Real, but out of scope for this guard to fix: whoever wires a live
    # miner is responsible for actually constructing it with
    # `config_for(band)`. All this can do is notice, from the outside, when
    # it looks like nobody did — never silently, and never by refusing to run.
    wiring_note: str | None = None
    if miner is not None:
        miner_cfg = getattr(miner, "config", None)
        if miner_cfg is not None and miner_cfg != config_for(band):
            wiring_note = (
                "the injected miner's config does not match config_for(band) for "
                f"the {band.name!r} band — it may not be wired to this topic's spend band"
            )

    if not stopped:
        if miner is not None:
            # `campaign_id` is the vendored miner's name for what this fork
            # calls a topic. They are the same value; both land on the row
            # (see below).
            outcome = miner.run(campaign_id=topic.topic_id, clusters=clusters)
            try:
                cap.spend(max(0.0, outcome.cost_usd - estimate.total_usd))
            except BudgetExceeded as exc:
                # The sweep has already run and already spent real money — a
                # breach caught here is the cap catching up to a bill that
                # came in higher than estimated, not a purchase we can still
                # decline. The rows already collected are kept (below):
                # "partial rows, a recorded deferral, no overspend, no
                # exception thrown at the pipeline" is the vendored miner's
                # own contract for an internal stop, and this is that same
                # contract applied one level up.
                stopped, reason = True, str(exc)
        else:
            # Absent data, stated: zero rows and zero cost because nothing
            # was ever asked to sweep, not because a sweep came back empty.
            reason = "no miner supplied — nothing was swept"

    rows: list[dict[str, Any]] = []
    if outcome is not None:
        for row in outcome.rows:
            enriched = dict(row)
            # `campaign_id` is already on the row — the vendored `build_row`
            # puts it there, and the parity fixtures assert on it, so it stays.
            # `topic_id` is this fork's name for the same value and is what
            # every analysis pass reads. Equal by construction, and the spec
            # (§3.1) names `topic_id` as the key build_row gains.
            enriched["topic_id"] = topic.topic_id
            enriched["snapshot_at"] = run.started_at
            rows.append(enriched)

    store.write_artifact(run.run_id, "signals.json", rows)
    store.write_artifact(
        run.run_id,
        "provenance.json",
        {
            # These are two different things: `provider` is the vendor name
            # (`outcome.provider`, e.g. "brightdata"), `provenance` is the
            # detail dict. Collapsing them into one "provider" key holding the
            # dict — the previous shape here — silently dropped the string.
            "provider": outcome.provider if outcome is not None else None,
            "provenance": outcome.provenance if outcome is not None else {},
            "queries_run": list(getattr(outcome, "queries_run", [])) if outcome else [],
            "calls": list(getattr(outcome, "calls", [])) if outcome else [],
            "denied": list(getattr(outcome, "denied", [])) if outcome else [],
            "deferrals": list(getattr(outcome, "deferrals", [])) if outcome else [],
        },
    )
    attempted = list(getattr(outcome, "venues_attempted", [])) if outcome else []
    collected = list(getattr(outcome, "venues_collected", [])) if outcome else []
    restricted = list(getattr(outcome, "venues_restricted", [])) if outcome else []
    notes = list(outcome.notes) if outcome is not None else []
    if wiring_note is not None:
        notes = [*notes, wiring_note]
    store.write_artifact(
        run.run_id,
        "coverage.json",
        {
            "venues_attempted": attempted,
            "venues_collected": collected,
            # Named explicitly: a venue that answered with nothing is a
            # finding, and a silent filter is indistinguishable from finding
            # nothing — but a Tier-C host is neither: `attempted` is seeded
            # with the restricted set even though it was never queried at
            # all, so it must be excluded here, not just listed separately.
            # Leaving it in would call a host "attempted and empty" that was
            # in fact refused before any request went out — a false
            # statement in a coverage artifact, the same class of bug Task 2
            # fixed for `tier_c_refused`.
            "venues_empty": sorted(set(attempted) - set(collected) - set(restricted)),
            "venues_restricted": restricted,
            # The vendored miner's per-host tier + robots record — its only
            # writer is MINE, and without this key here, spec decision D5's
            # "recorded per host in coverage" is simply unmet.
            "hosts": list(outcome.coverage) if outcome is not None else [],
            "notes": notes,
        },
    )
    # Both figures are real, never invented, and neither is zeroed out just
    # because the run stopped: `actual_usd` is what the sweep really cost
    # (genuinely zero if it never ran — nothing was bought), `model_usd` is
    # what the lexicon call really cost (genuinely zero if no client was
    # used). `cap.spent()` below is a different number on purpose — it is
    # what the *cap* accepted, which can be less than what was actually
    # spent when a breach is discovered after the money already went out;
    # collapsing the two would either hide a real bill or invent a smaller
    # one, and both are the failure this guard exists to prevent.
    #
    # Direct attribute access, not `getattr(..., 0.0)`: `outcome` is already
    # known non-`None` here, so a rename on `cost_usd` must raise rather than
    # silently report a zero that reads exactly like "the sweep was free".
    actual_usd = round(outcome.cost_usd, 6) if outcome is not None else 0.0
    store.write_artifact(
        run.run_id,
        "cost.json",
        {
            "estimate_usd": estimate.total_usd,
            "breakdown": estimate.breakdown,
            "actual_usd": actual_usd,
            "model_usd": lexicon_usd,
            "cap_usd": cap.cap_usd,
            "spent_usd": cap.spent(),
            "stopped": stopped,
            "reason": reason,
        },
    )
    store.write_artifact(
        run.run_id, "plan.json",
        {"clusters": clusters, "plan": list(getattr(outcome, "plan", [])) if outcome else []},
    )

    return store.finish(
        run.run_id,
        "stopped_on_budget" if stopped else "complete",
        # The run's recorded cost is the real total (lexicon + sweep), not
        # `cap.spent()` — by the time either figure is known, that money has
        # already been spent regardless of what the cap decided to accept.
        cost_usd=round(lexicon_usd + actual_usd, 6),
        note=reason,
    )
