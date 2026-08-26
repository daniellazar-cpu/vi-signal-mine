"""INSIGHT — one snapshot in, seven artifacts out.

Each pass writes as soon as it finishes, so a failure late in the chain still
leaves the earlier work on disk and re-running is cheap.

**Resumable by default (spec D17).** INSIGHT is the mode most likely to hit a
Vercel function's timeout — several model passes over every signal in a
large snapshot, on a platform that (per D14) restricts a *live sweep* to the
cheapest band but places no such limit on how big a snapshot INSIGHT is
asked to analyse. ``resume=True`` means a re-request after a timeout costs
exactly the passes that had not finished, not the ones that had: before each
pass runs, this checks whether its artifact is already on this run, and if
so reads it back rather than recomputing (and re-billing) it. A resumed run
produces the identical seven artifacts an unresumed one would — the only
difference is which passes were actually recomputed, provable by an
untouched artifact keeping both its original bytes and its original mtime
(see ``tests/test_insight_resume.py``).

Two passes' outputs are needed by later passes in the same run, not just
written to disk: ``themes`` (by stance, dual-lens, momentum, anomaly and
corroboration) and ``stances`` (by dual-lens). Skipping either pass's
computation therefore means reconstructing its dataclasses from the artifact
already on disk, not just noting that the file exists.

``priors`` — the reclustered history momentum and anomaly both compare
against — is itself a model cost (one ``cluster_themes`` call per earlier
snapshot) and is computed lazily, once, only when at least one of those two
passes still needs to run. A resumed run where both are already on disk
never touches it at all.

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
from vsm.analysis.cluster import Theme, cluster_themes
from vsm.analysis.corroborate import corroborate
from vsm.analysis.duallens import dual_lens
from vsm.analysis.momentum import momentum
from vsm.analysis.resolve import build_lexicon, resolve_signals
from vsm.analysis.stance import ThemeStance, stance_for_themes
from vsm.mining.signals import any_synthetic
from vsm.runs.model import Run
from vsm.runs.store import RunStore
from vsm.topics.model import Topic

__all__ = ["run_insight"]


def _existing_artifact(store: RunStore, run_id: str, name: str) -> Any | None:
    """The artifact's contents if it is already on this run, else ``None``.

    A plain ``try/read/except`` rather than an ``artifacts_dir(...).exists()``
    check: it works identically against any ``RunStoreLike`` backend (the
    filesystem pair and Task 24's Postgres-plus-blob pair alike) using only
    methods the protocol already guarantees, and callers that need the
    reconstructed value (``themes``, ``stances``) get it from the same call
    that decided whether to skip.
    """
    try:
        return store.read_artifact(run_id, name)
    except FileNotFoundError:
        return None


def _theme_from_dict(d: dict[str, Any]) -> Theme:
    return Theme(
        theme_id=d["theme_id"],
        name=d["name"],
        signal_ids=tuple(d["signal_ids"]),
        volume=d["volume"],
        venue_mix=dict(d["venue_mix"]),
        kind_mix=dict(d["kind_mix"]),
    )


def _stance_from_dict(d: dict[str, Any]) -> ThemeStance:
    return ThemeStance(
        theme_id=d["theme_id"], by_class=dict(d["by_class"]), basis=d["basis"]
    )


def _tagged(rows: list[dict[str, Any]], synthetic: bool) -> list[dict[str, Any]]:
    """The safety rail, propagated: every item in an INSIGHT list-artifact
    carries ``synthetic: True`` when any signal in the snapshot it was built
    from is fabricated. Additive only — every existing key and value is
    untouched, so ``_theme_from_dict``/``_stance_from_dict`` (which read only
    the keys they name) are unaffected on a resumed run — and absent
    entirely when ``synthetic`` is ``False``, the same "present only when
    true" shape :func:`vsm.mining.signals.build_row` uses: the marker must
    not be permanently on.
    """
    if not synthetic:
        return rows
    return [{**row, "synthetic": True} for row in rows]


def _existing_insight_run(
    store: RunStore, topic_id: str, snapshot_run_id: str
) -> Run | None:
    """The most recent INSIGHT run already covering this snapshot, if any.

    Looked up unconditionally — not gated on ``resume`` — because ``resume``
    is a decision about whether *a pass already on this run* gets skipped,
    and that only means something once "this run" names the same run every
    call for the same snapshot makes. Without this lookup, every call would
    start a fresh run via ``store.start`` and the per-artifact skip check
    would never find anything to skip, since a brand-new run's artifact
    directory is always empty — ``resume`` would be a parameter that did
    nothing. One INSIGHT run per (topic, snapshot) is also the right product
    shape: "analyse this snapshot" is idempotent, not a request for a fresh,
    independent second opinion each time the button is clicked.
    """
    matches = [
        r for r in store.for_topic(topic_id, "insight")
        if r.parent_run_id == snapshot_run_id
    ]
    return matches[-1] if matches else None


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
    resume: bool = True,
    run_id: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> Run:
    resolver = resolver or VenueResolver()
    # See vsm.modes.mine.run_mine's identical comment: these three overrides
    # exist only for vsm.demo.seed_demo_topic, are `None` for every real
    # caller, and are spread in as an empty dict in that case so this still
    # works against a backend (PostgresRunStore) whose start()/finish() have
    # no such parameters at all.
    start_overrides = {
        k: v for k, v in {"run_id": run_id, "started_at": started_at}.items()
        if v is not None
    }
    finish_overrides = {"finished_at": finished_at} if finished_at is not None else {}
    # Snapshot the client's cumulative total before any pass runs, so the cost
    # recorded against this run is its own and not the client's whole history.
    # A resumed run only pays for the passes it actually recomputes: spend
    # already billed to an earlier attempt is not re-counted just because
    # this call also produced the artifact set.
    spend_before = client.spend.usd if client is not None else 0.0
    run = _existing_insight_run(store, topic.topic_id, snapshot_run_id) or store.start(
        topic.topic_id, "insight", parent_run_id=snapshot_run_id, **start_overrides
    )
    signals = store.read_artifact(snapshot_run_id, "signals.json")
    # The safety rail. Computed once, from the snapshot this INSIGHT run
    # analyses, and threaded into every artifact written below — see
    # _tagged() and vsm.mining.signals.any_synthetic.
    synthetic = any_synthetic(signals)

    def _existing(name: str) -> Any | None:
        return _existing_artifact(store, run.run_id, name) if resume else None

    # --- entities: standalone, nothing downstream reads it back -----------
    if _existing("entities.json") is None:
        entities = build_lexicon(topic)
        payload = resolve_signals(signals, entities)
        if synthetic:
            payload = {**payload, "synthetic": True}
        store.write_artifact(run.run_id, "entities.json", payload)

    # --- themes: needed in memory by every pass below ----------------------
    existing_themes = _existing("themes.json")
    if existing_themes is not None:
        themes = [_theme_from_dict(d) for d in existing_themes]
    else:
        themes = cluster_themes(signals, client=client)
        store.write_artifact(
            run.run_id, "themes.json", _tagged([asdict(t) for t in themes], synthetic)
        )

    # --- stance: needed in memory by dual-lens ------------------------------
    existing_stances = _existing("stance.json")
    if existing_stances is not None:
        stances = [_stance_from_dict(d) for d in existing_stances]
    else:
        stances = stance_for_themes(themes, signals, resolver, client=client)
        store.write_artifact(
            run.run_id, "stance.json", _tagged([asdict(s) for s in stances], synthetic)
        )

    # --- dual-lens: standalone ----------------------------------------------
    if _existing("duallens.json") is None:
        store.write_artifact(
            run.run_id, "duallens.json",
            _tagged([asdict(g) for g in dual_lens(themes, stances)], synthetic),
        )

    # --- momentum & anomaly: share `priors`, computed at most once ---------
    # `priors` reclusters every earlier snapshot's signals — a real model
    # cost per snapshot — so it is fetched only if at least one of the two
    # passes that need it still has to run. A run resumed after both are
    # already on disk never touches it.
    need_momentum = _existing("momentum.json") is None
    need_anomaly = _existing("anomaly.json") is None
    if need_momentum or need_anomaly:
        priors = _prior_snapshot_themes(topic, store, snapshot_run_id, client)

    if need_momentum:
        store.write_artifact(
            run.run_id, "momentum.json",
            _tagged([asdict(m) for m in momentum(themes, priors)], synthetic),
        )

    if need_anomaly:
        anomalies = narrate(detect_anomalies(themes, priors), client=client)
        store.write_artifact(
            run.run_id, "anomaly.json", _tagged([asdict(a) for a in anomalies], synthetic)
        )

    # --- corroboration: standalone -----------------------------------------
    # Per-theme corroboration strength, recorded as INFORMATION (spec D18).
    # This is not a gate: a theme is always reportable, because its volume and
    # stance are counts and a count needs no corroboration. G6 runs in REPORT
    # over the claims the report writes, which is where three independent
    # sources is the right bar.
    if _existing("findings.json") is None:
        by_id = {str(s["signal_id"]): s for s in signals}
        findings = corroborate(
            [{"statement": t.name, "signal_ids": list(t.signal_ids)} for t in themes], by_id
        )
        store.write_artifact(
            run.run_id, "findings.json", _tagged([asdict(f) for f in findings], synthetic)
        )

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
    return store.finish(run.run_id, "complete", cost_usd=spend, **finish_overrides)
