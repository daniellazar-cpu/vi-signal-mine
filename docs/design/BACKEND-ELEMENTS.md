# Backend elements

Every entity, field and computed value the system actually holds. No interface
copy, no page names, no current layout. This is the raw material a UI could be
built from.

**Internal names are given as-is and should be treated as provisional.** They
were chosen by engineers for engineers. Several are opaque to anyone outside
this codebase — `corroborated`, `NE`, `probe band`, `tier`, `dual-lens` — and
renaming them is expected, not forbidden.

---

## 1. Topic

The unit that persists and accumulates history. Everything else hangs off one.

| Field | Type | Notes |
|---|---|---|
| `topic_id` | string | `top-` + 10 hex |
| `name` | string | The only field a user must supply |
| `therapeutic_area` | string | Optional, free text |
| `spend_band` | enum | `probe` / `standard` / `deep` |
| `created_at` | ISO 8601 | |
| `brand` | string / null | Optional |
| `molecule` | string / null | Optional |
| `competitors` | string[] | Optional |
| `questions` | string[] | Free-text questions the user wants answered |
| `never_say` | string[] | Terms the output may never contain. Enforced |

**Spend band** is a cost/coverage dial with four numeric knobs:
`queries_per_cluster`, `serp_results_per_query`, `discover_results_per_cluster`,
`page_fetches_per_cluster`. One page fetch costs ~20× a search call, so that
last number sets the bill.

---

## 2. Run

One execution. A topic has many, ordered, and they chain: a MINE produces the
input to an INSIGHT, which produces the input to a REPORT.

| Field | Type | Notes |
|---|---|---|
| `run_id` | string | prefixed `min-` / `ins-` / `rep-` |
| `topic_id` | string | parent |
| `mode` | enum | `mine` / `insight` / `report` |
| `status` | enum | `running` / `complete` / `failed` / `stopped_on_budget` |
| `started_at`, `finished_at` | ISO 8601 | |
| `cost_usd` | float | real money |
| `parent_run_id` | string / null | the chain link |
| `note` | string | |

`stopped_on_budget` is a **successful partial**, not a failure: rows collected
before the cap are kept.

---

## 3. Signal — the atomic collected row

One post, article, or page. Everything else in the system is an aggregate of
these. ~27 fields:

**Identity / provenance**
`signal_id`, `url`, `venue` (registrable domain), `captured_at`, `snapshot_at`,
`posted_at`, `collection_method` (`api` / `serp_result` / `public_web_fetch`),
`collection_tier` (`A`/`B`/`C`), `tos_basis`, `dedupe_hash`, `campaign_id`,
`topic_id`, `cluster_id`, `_query` (the exact query string that found it)

**Content**
`excerpt`, `matched_terms`, `brand_mentioned` (bool), `theme`

**Interpretation** (may be null — nullability is meaningful)
`sentiment`, `intent_score`, `action`, `distribution_mode`,
`author_type` (`hcp` / `patient` / `institutional` / `unknown`),
`author_type_confidence`, `author_type_rationale`

**Reach**
`engagement` — free-shape dict, in practice `{upvotes, replies}`

**Integrity**
`synthetic` (bool) — true when fabricated by the offline miner. Propagates into
every downstream artifact and every exported file.

---

## 4. Venue — the source registry

A curated list, not discovered at runtime.

| Field | Notes |
|---|---|
| `domain`, `name` | |
| `kind` | `evidence` / `guideline_body` / `hcp_discussion` / `patient_community` / `regulatory` / `drug_reference` |
| `collection_tier` | A / B / C — how the venue may be collected |
| `api_available` | bool |
| `tos_posture` | what the terms permit |
| `robots` | literal robots.txt content at a verified date |
| `areas` | therapeutic areas it covers |

**Band** (1 conversation / 2 opinion / 3 substrate) is a *separate axis* from
kind, and drives query order and budget.

`hcp_discussion` and `patient_community` are date-windowed — a 2019 forum thread
is not current practice.

---

## 5. Artifacts — the outputs, per run

### MINE
- **`signals.json`** — list of Signal (above)
- **`coverage.json`** — `venues_attempted`, `venues_collected`, `venues_empty`,
  `venues_restricted`, `hosts`, `notes`. *A venue that returned nothing is named,
  because a silent filter is indistinguishable from finding nothing.*
- **`cost.json`** — `estimate_usd`, `cap_usd`, `spent_usd`, `actual_usd`,
  `model_usd`, `stopped` (bool), `reason`, `breakdown[]`

### INSIGHT — seven passes
- **`entities.json`** — `entities`, `by_signal`, `unmapped_mentions`
- **`themes.json`** — `theme_id`, `name`, `volume`, `signal_ids[]`,
  `venue_mix`, `kind_mix`
- **`findings.json`** — `finding_id`, `statement`, `independent_sources` (int),
  `tier`, `signal_ids[]`, `unresolved_ids[]`
  - `tier` ∈ `corroborated` (≥3 independent sources) / `emerging` (2) /
    `single_source` (1). **"Independent" has a precise definition**: a true
    forum counts one *post* as one source; every other venue counts one
    *publisher* as one source, however many pages it runs. This stops five
    outlets syndicating one press release from reading as five sources.
- **`stance.json`** — `theme_id`, `by_class` (nested counts), `basis`.
  Stance ∈ `positive` / `negative` / `mixed` / `neutral` / `unclear`
- **`duallens.json`** — `theme_id`, `theme_name`, `hcp` (counts),
  `patient` (counts), `hcp_net` (float), `patient_net` (float),
  `divergence` (float **or null**), `reason`
  - **null divergence is the important case**: only one audience discussed the
    theme, so there is no gap. Rendering it as 0 would say the two agree.
- **`momentum.json`** — `theme_name`, `volume_prior`, `volume_now`, `delta`,
  `delta_pct`, `reason`. `volume_prior` null = no baseline.
- **`anomaly.json`** — `anomaly_id`, `kind`, `theme_name`, `observed`,
  `baseline`, `detail`. `kind` ∈ `theme_appeared` / `theme_vanished` /
  `volume_spike` / `volume_collapse`

### REPORT
Four prose documents plus provenance:
`pulse_report.md`, `provenance_appendix.md`, `methodology.md`,
`worth_considering.md`

---

## 6. Derived values that exist but are not first-class

Computable from the above, currently only assembled ad hoc:

- signal volume per topic per snapshot (a time series)
- spend per topic, per run, cumulative
- venue mix and kind mix per theme
- share of signals with a resolved `author_type`
- corroboration ratio (how many findings clear the 3-source bar)
- count of themes not comparable across the two audiences
- engagement totals per theme or venue
- collection tier distribution
- time between snapshots

---

## 7. Guards — hard rules the output must satisfy

| Rule | Effect |
|---|---|
| G1 | Every claim must carry citations to signal ids |
| G2 | Suggestions are advisory, never instructions |
| G3 | A run stops at its spend cap and keeps what it has |
| G4 | `never_say` terms may not appear in any generated string |
| G5 | No forecasting |
| G6 | A claim may only be stated at the confidence its source count supports |

Violations block output rather than degrade it.

---

## 8. Cardinality, realistically

- Topics: 1–200
- Runs per topic: 3–60
- Signals per snapshot: 10–500
- Themes per insight: 3–15
- Findings per insight: 3–20
- Venues in the registry: ~40

---

## 9. Constraints on any interface

- Server-rendered HTML, no build step, **no JavaScript required**
- No CDN, no external fonts, no external requests of any kind
- Must render with zero network
- Every figure must trace to a dated row with a URL
- A null must never render as a zero
