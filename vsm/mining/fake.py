"""The offline miner — a rehearsal, not an approximation, of the paid one.

Adapted from the parent's ``DeterministicMiner``
(``forum-engine/engine/orchestrator/stages.py``). Three differences from that
reference implementation, all deliberate:

1. **It draws venues from the real gold list**
   (:data:`vsm.mining.venues.GOLD_VENUES`), not the parent's reserved
   ``.example`` fixture hosts. An unregistered domain has no venue kind, so
   the parent's approach makes ``author_type`` come out ``unknown`` and the
   dual-lens gap come out ``NE`` for every row — honest about what the
   *parent's* fixture is, but useless as a demonstration of what *this*
   tool's routing, author-class and dual-lens machinery actually do. Real
   gold-list domains exercise all of it for real.
2. **It walks the query plan through venue-group boundaries, not a flat
   catalogue.** A gold query is scoped to a specific ``site:`` set — the
   venues :func:`~vsm.mining.queries.plan_queries` actually put in that
   query's ``PlannedQuery.venues`` — so a synthetic row only ever claims to
   come from a venue its query could plausibly have returned. Round-robining
   by venue *kind* within that set (rather than one flat random draw) is
   what reliably spreads rows across ``hcp_discussion`` and
   ``patient_community`` when a query's venue group spans both, which is
   what gives the dual-lens gap something real to compare.
3. **Every row is marked.** ``build_row(..., synthetic=True)`` — see
   :mod:`vsm.mining.signals`. Fabricated rows on real, well-known domains are
   exactly the "plausible enough to survive review" danger this codebase has
   fought throughout; the flag is what keeps this adaptation honest.

Still true of the parent's design, unchanged here:

* **It walks the same plan the live miner walks** —
  :func:`vsm.mining.queries.plan_queries`, including the same
  :func:`~vsm.mining.queries.gold_under_delivered` decision about the
  open-web tail. That is what makes an offline run a rehearsal of the paid
  one rather than an approximation.
* **Deterministic in campaign_id + cluster + query.** A re-run is
  byte-identical — no wall clock, no randomness, nothing read from the
  environment.
* **Tier-C is never drawn from.** Every venue this miner can select is
  already tier A/B (the gold list's collection tier, not this run's
  behaviour); nothing here needs — or has — an enforcement flag.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from vsm.mining.miner import MiningOutcome
from vsm.mining.queries import MIN_GOLD_ROWS, PlannedQuery, gold_under_delivered, plan_queries
from vsm.mining.signals import Hit, build_row, dedupe_rows, tos_basis_for
from vsm.mining.venues import GOLD_VENUES, Venue, venue_for

__all__ = ["DeterministicMiner"]

#: Themes a synthetic row can land in. Lifted from the parent verbatim — they
#: read as plausible clinical-operations concerns without naming a therapeutic
#: area, which is the point: a demonstration theme, not a clinical claim.
_THEMES: tuple[str, ...] = (
    "titration burden between visits",
    "monitoring cadence when labs are missed",
    "which patients to escalate first",
    "counselling time in a 12-minute visit",
    "documentation and prior authorisation friction",
)

_DEFAULT_CLOCK = datetime(2026, 7, 31, tzinfo=timezone.utc)


def _seed_int(*parts: Any) -> int:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def _synthetic_url(domain: str, seed: int) -> str:
    """A path a reader can tell at a glance was never fetched.

    Rides on a *real* gold-list domain — that is what exercises venue-kind
    and author-class routing for real — but the path is deliberately not a
    plausible article slug: ``/synthetic-demo/not-fetched-<n>`` cannot be
    mistaken for something this tool actually collected.
    """
    return f"https://{domain}/synthetic-demo/not-fetched-{seed % 999983}"


class DeterministicMiner:
    """Offline fake for the mining layer. Same shape as the real thing, no
    network — see :meth:`run` for the interface :class:`LiveSignalMining`
    also implements.
    """

    provider = "deterministic-fake"

    def __init__(
        self,
        *,
        queries_per_cluster: int = 4,
        rows_per_query: int = 3,
        clock: Any = None,
    ) -> None:
        #: matches ``LiveSignalMining``'s ``MiningConfig.queries_per_cluster``
        #: being CONSTRUCTOR state, not a ``run()`` argument — a caller who
        #: wants a spend-band-sized demonstration builds this with
        #: ``queries_per_cluster=band.queries_per_cluster`` (see
        #: ``vsm.mining.get_miner``) rather than passing it to ``run()``.
        self.queries_per_cluster = max(1, int(queries_per_cluster))
        self.rows_per_query = max(1, int(rows_per_query))
        # A fixed default, never ``datetime.now()``: determinism in
        # campaign_id + cluster + query is the whole point of this class, and
        # a wall-clock captured_at would make every re-run of the same topic
        # produce different bytes for no reason a test — or an operator
        # diffing two "identical" snapshots — could explain.
        self.clock = clock or (lambda: _DEFAULT_CLOCK)
        self._collectable: tuple[Venue, ...] = tuple(
            v for v in GOLD_VENUES if v.collection_tier in ("A", "B")
        )

    # ------------------------------------------------------------------ run
    def run(
        self,
        *,
        campaign_id: str,
        clusters: Sequence[Mapping[str, Any]],
        queries_per_cluster: int | None = None,
    ) -> MiningOutcome:
        """Same signature as :meth:`LiveSignalMining.run`, same return type."""
        per_cluster = int(queries_per_cluster) if queries_per_cluster else self.queries_per_cluster
        captured_at = self.clock()
        outcome = MiningOutcome(provider=self.provider)
        rows: list[dict[str, Any]] = []
        attempted: set[str] = set()

        for cluster in clusters:
            plan = plan_queries(cluster, per_cluster)
            gold = [p for p in plan if p.kind == "gold"]
            tail = [p for p in plan if p.kind == "open"]

            gold_rows = 0
            for planned in gold:
                attempted.update(planned.venues)
                outcome.plan.append(planned.as_dict())
                outcome.queries_run.append(planned.text)
                new_rows = self._rows_for(campaign_id, cluster, planned, captured_at)
                rows.extend(new_rows)
                gold_rows += len(new_rows)

            # The same "did the gold list under-deliver?" decision the live
            # miner makes (vsm.mining.queries.gold_under_delivered) — an
            # offline rehearsal that spent the open-web tail whenever the
            # live one would not is not a rehearsal, it is a different sweep.
            if tail and gold_under_delivered(gold_rows, minimum=MIN_GOLD_ROWS):
                outcome.notes.append(
                    f"gold list under-delivered ({gold_rows} rows < {MIN_GOLD_ROWS}) for "
                    f"cluster {cluster.get('cluster_id')} — rehearsing {len(tail)} "
                    "open-web quer" + ("y" if len(tail) == 1 else "ies")
                )
                for planned in tail:
                    outcome.plan.append(planned.as_dict())
                    outcome.queries_run.append(planned.text)
                    rows.extend(self._rows_for(campaign_id, cluster, planned, captured_at))
            elif tail:
                outcome.notes.append(
                    f"gold list delivered {gold_rows} rows for cluster "
                    f"{cluster.get('cluster_id')} — the {len(tail)} open-web quer"
                    f"{'y' if len(tail) == 1 else 'ies'} in the plan were not run"
                )

        outcome.rows = dedupe_rows(rows)
        collected = sorted({str(r["venue"]) for r in outcome.rows if r.get("venue")})
        outcome.venues_collected = collected
        outcome.venues_attempted = sorted(attempted | set(collected))
        outcome.venues_restricted = []  # never drawn from — see class docstring
        outcome.cost_usd = 0.0
        outcome.notes.append(
            "synthetic sweep (deterministic offline miner) — every row is fabricated "
            "for rehearsal; no page was fetched and no request left this process"
        )
        outcome.provenance = {
            "synthetic": True,
            "reason": (
                "VSM_OFFLINE=1 or VSM_MINER=fake — the deterministic demonstration "
                "miner ran instead of Bright Data; nothing on this run was collected "
                "from the web"
            ),
        }
        return outcome

    # -------------------------------------------------------------- helpers
    def _venues_for(self, planned: PlannedQuery) -> list[Venue]:
        """The venues one planned query could plausibly have returned.

        For a gold query this is exactly the ``site:``-scoped set the query
        actually carries (``planned.venues``, resolved back to
        :class:`~vsm.mining.venues.Venue`) — a synthetic row never claims a
        venue its own query would not have targeted. The open-web tail has no
        such scope by construction, so it draws from every collectable
        gold-list venue instead, which is the closest honest analogue to "the
        open web returned something on the gold list".
        """
        if planned.kind == "gold" and planned.venues:
            found = [venue_for(d) for d in planned.venues]
            return [v for v in found if v is not None and v.collection_tier in ("A", "B")]
        return list(self._collectable)

    def _rows_for(
        self,
        campaign_id: str,
        cluster: Mapping[str, Any],
        planned: PlannedQuery,
        captured_at: datetime,
    ) -> list[dict[str, Any]]:
        venues = self._venues_for(planned)
        if not venues:
            return []
        # Round-robin by venue *kind*, not one flat draw over the group: a
        # query whose site: scope spans hcp_discussion and patient_community
        # (the conversation band routinely does — see vsm.mining.venues)
        # only actually demonstrates the dual-lens gap if a synthetic row
        # lands in both, and a single hashed pick over the whole group has no
        # reason to hit both when rows_per_query is small.
        kinds = list(dict.fromkeys(v.kind for v in venues))
        by_kind: dict[str, list[Venue]] = {k: [v for v in venues if v.kind == k] for k in kinds}
        # One theme per query, not one per row: a query is one angle of
        # inquiry, and every row it produces — whatever venue kind answered —
        # belongs to that same angle. This is also what gives the dual-lens
        # pass something to compare: an hcp_discussion row and a
        # patient_community row drawn from the same mixed-kind query land in
        # the same theme bucket, deterministically, rather than by chance.
        theme = _THEMES[_seed_int(campaign_id, cluster.get("cluster_id"), planned.text) % len(_THEMES)]

        rows: list[dict[str, Any]] = []
        for i in range(self.rows_per_query):
            kind = kinds[i % len(kinds)]
            pool = by_kind[kind]
            seed = _seed_int(campaign_id, planned.text, i)
            venue = pool[seed % len(pool)]
            rows.append(self._row(campaign_id, cluster, planned, i, venue, theme, seed, captured_at))
        return rows

    def _row(
        self,
        campaign_id: str,
        cluster: Mapping[str, Any],
        planned: PlannedQuery,
        index: int,
        venue: Venue,
        theme: str,
        seed: int,
        captured_at: datetime,
    ) -> dict[str, Any]:
        entry = venue.as_catalogue_entry()
        hit = Hit(
            url=_synthetic_url(venue.domain, seed),
            # derive_theme() strips a trailing "| site name" and lower-cases;
            # _THEMES is already a short lower-case phrase, so it survives
            # unchanged and row["theme"] comes out exactly `theme`.
            title=theme,
            description=(
                f"Synthetic demonstration row — no page was fetched. Rehearses a "
                f"{planned.kind}-list query ({planned.text!r}) against {venue.name}."
            ),
            collection_method="api" if venue.api_available else "public_web_fetch",
            collection_tier=venue.collection_tier,
            distribution_mode=venue.distribution_mode,
            patient_generated=venue.patient_generated,
            posted_at=None,
            engagement={"upvotes": seed % 43, "replies": seed % 11},
            query=planned.text,
        )
        hit.tos_basis = tos_basis_for(
            venue_entry=entry,
            robots_summary="robots.txt not consulted — synthetic row, no fetch performed",
            method=hit.collection_method,
            checked_at=captured_at,
        )
        return build_row(
            campaign_id=campaign_id,
            cluster=cluster,
            hit=hit,
            captured_at=captured_at,
            synthetic=True,
        )
