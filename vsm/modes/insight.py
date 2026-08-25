"""INSIGHT — one snapshot in, seven artifacts out.

Each pass writes as soon as it finishes, so a failure late in the chain still
leaves the earlier work on disk and re-running is cheap.

**History means what came before.** The baseline is built only from snapshots
earlier in the series than this one; if it included later ones, the same
snapshot would produce different deltas depending on when the insight run
happened, which would make every number in the report a function of the
operator's schedule.

"Earlier" is decided by the store's monotonic sequence, not by comparing
``started_at``. Two snapshots created in the same microsecond compare equal on
a timestamp, and the baseline would silently lose one.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from vsm.analysis.anomaly import detect_anomalies, narrate
from vsm.analysis.authorclass import VenueResolver
from vsm.analysis.cluster import cluster_themes
from vsm.analysis.corroborate import corroborate
from vsm.analysis.duallens import dual_lens
from vsm.analysis.momentum import momentum
from vsm.analysis.resolve import build_lexicon, resolve_signals
from vsm.analysis.stance import stance_for_themes
from vsm.runs.model import Run
from vsm.runs.store import RunStore
from vsm.topics.model import Topic

__all__ = ["run_insight"]


def _prior_snapshot_themes(
    topic: Topic, store: RunStore, snapshot_run_id: str, client: Any | None
) -> list[list[Any]]:
    """Themes from every completed MINE run that started before this one.

    Ordered by the store's monotonic sequence, never by wall-clock time: two
    snapshots created in the same microsecond would otherwise compare equal
    and silently drop a baseline.
    """
    series = store.snapshots(topic.topic_id)
    try:
        position = [r.run_id for r in series].index(snapshot_run_id)
    except ValueError:
        # This snapshot is not a completed MINE run of this topic, so it has
        # no place in the series and therefore no history.
        return []
    earlier = series[:position]
    out: list[list[Any]] = []
    for run in earlier:
        try:
            rows = store.read_artifact(run.run_id, "signals.json")
        except FileNotFoundError:
            continue
        out.append(cluster_themes(rows, client=client))
    return out


def run_insight(
    topic: Topic,
    snapshot_run_id: str,
    store: RunStore,
    *,
    client: Any | None = None,
    resolver: Any | None = None,
) -> Run:
    resolver = resolver or VenueResolver()
    # Snapshot the client's cumulative total before any pass runs, so the cost
    # recorded against this run is its own and not the client's whole history.
    spend_before = client.spend.usd if client is not None else 0.0
    run = store.start(topic.topic_id, "insight", parent_run_id=snapshot_run_id)
    signals = store.read_artifact(snapshot_run_id, "signals.json")

    entities = build_lexicon(topic)
    store.write_artifact(run.run_id, "entities.json", resolve_signals(signals, entities))

    themes = cluster_themes(signals, client=client)
    store.write_artifact(run.run_id, "themes.json", [asdict(t) for t in themes])

    stances = stance_for_themes(themes, signals, resolver, client=client)
    store.write_artifact(run.run_id, "stance.json", [asdict(s) for s in stances])

    store.write_artifact(
        run.run_id, "duallens.json", [asdict(g) for g in dual_lens(themes, stances)]
    )

    priors = _prior_snapshot_themes(topic, store, snapshot_run_id, client)
    store.write_artifact(
        run.run_id, "momentum.json", [asdict(m) for m in momentum(themes, priors)]
    )

    anomalies = narrate(detect_anomalies(themes, priors), client=client)
    store.write_artifact(run.run_id, "anomaly.json", [asdict(a) for a in anomalies])

    # Per-theme corroboration strength, recorded as INFORMATION (spec D18).
    # This is not a gate: a theme is always reportable, because its volume and
    # stance are counts and a count needs no corroboration. G6 runs in REPORT
    # over the claims the report writes, which is where three independent
    # sources is the right bar.
    by_id = {str(s["signal_id"]): s for s in signals}
    findings = corroborate(
        [{"statement": t.name, "signal_ids": list(t.signal_ids)} for t in themes], by_id
    )
    store.write_artifact(run.run_id, "findings.json", [asdict(f) for f in findings])

    # Charge THIS RUN's model spend, which is a delta, not the client's total.
    # `client.spend` is a cumulative ledger for the client's whole life, so a
    # client shared across two runs — an INSIGHT after a MINE is the obvious
    # wiring — would bill the first run's spend to the second.
    #
    # Read directly, never through `getattr` with a default: a cost of 0.0
    # produced by a renamed attribute is indistinguishable from a run that
    # genuinely spent nothing, and this is the number an operator trusts to
    # know what they spent. A rename must raise, not round to zero.
    spend = round(client.spend.usd - spend_before, 6) if client is not None else 0.0
    return store.finish(run.run_id, "complete", cost_usd=spend)
