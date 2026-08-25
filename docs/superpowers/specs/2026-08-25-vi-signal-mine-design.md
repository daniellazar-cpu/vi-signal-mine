# Vi Signal Mine — design

**Date:** 2026-08-25 · **Revision 2** · **Status:** approved for planning
**Owner:** Daniel Lazar
**Parent:** `daniellazar-cpu/attending-health-engine` (local: `~/Documents/forum-engine`)
**Research behind it:** `docs/research/2026-08-25-social-intelligence-landscape.md`

> **Revision 2 replaced revision 1's purpose, not just its details.** Revision 1
> described a content-generation tool, because the mechanism was lifted out of a
> content-generation product and the purpose came across with it unexamined. This
> is a **pulse instrument**: it watches what is being said about a brand or
> product online, and turns that into intelligence Vi can act on and hand to a
> client. Output is a read on the world, not material for a reader.

---

## 1. What this is

You give it a topic the way you would start an Attending Health campaign. It
goes out and collects what is being said — text, engagement, where, by which kind
of source. Then it corroborates, clusters, measures stance and movement, and
turns that into a report Vi can put in front of a client.

```
TOPIC  (persistent: brand · product · molecule · competitors · therapeutic area)
  │
  ├── MINE ───────▶ snapshot @ 2026-08-25   signals · provenance · coverage · cost
  ├── MINE ───────▶ snapshot @ 2026-09-01                  (a week later)
  │                        │
  │                        ▼
  ├── INSIGHT ────▶ corroborated findings · themes · stance by venue class
  │                 dual-lens gap · momentum vs prior snapshots · anomalies
  │                        │
  │                        ▼
  └── REPORT ─────▶ pulse report · provenance appendix · methodology statement
```

Three modes, any one runnable alone, each able to consume the previous.

### Why a topic, and not just a run

Momentum and anomaly are **deltas**, and a delta needs a baseline. A one-shot run
can tell you what is being said; only a series can tell you what is *changing*,
which is the half a client cannot get by reading Reddit themselves. So a topic
persists — its brief, its competitor set, its venue routing — and each MINE run
is a dated snapshot of it.

**On a topic's first snapshot there is no baseline.** Momentum and anomaly return
`null` with the reason `no prior snapshot`, and the report says so. This is the
parent engine's rule about not inventing numbers, applied to time.

## 2. Decisions on record

Decided with the owner on 2026-08-25. Recorded because several close off options
a later reader would otherwise reopen.

| # | Decision | Consequence |
|---|---|---|
| D1 | **Healthcare/pharma only.** | The gold-list venue registry, therapeutic-area routing and medical query shapes travel unchanged. |
| D2 | **Three chainable modes** — MINE · INSIGHT · REPORT. | Not per-stage start/stop. A run records its upstream run. |
| D3 | **Local-first, no auth.** | Runs on the operator's machine. Own keys via `.env`. No user table, no login, no multi-tenancy. |
| D4 | **Cost caps and the budget ledger travel.** | Estimate-before-spend, per-run USD cap, clean stop on breach. |
| D5 | **Tier-C blocklist and live robots.txt gating do NOT travel.** Raised as a concern, reaffirmed. | The miner collects from any host search returns. Robots state is still *recorded* per host in coverage — reporting, not gating. Refusal code stays behind a default-off flag so this is reversible without archaeology. |
| D6 | **The rung 0–5 claim ladder and 19 clinical QA checks do not travel.** | Output is intelligence, not a promotional asset needing claim classification. |
| D7 | **Purpose is pulse, not education.** Awareness of what is being said about a customer's brand or product online. | Superseded revision 1. Drives everything in §4–§5. |
| D8 | **v1 covers capability rungs 1–7** (see research §1): corpus, entity resolution, corroboration, clustering, stance, momentum, anomaly. | The dual-lens gap is in. Handle→NPI author identity is **out** (D9). |
| D9 | **Author class comes from the venue in v1, behind a resolver seam.** | v1 says "this is HCP-venue conversation"; it cannot say "this is Dr X, NPI 123". Every artifact records the **basis** alongside the class, so identity-derived resolution drops in without touching stance or dual-lens. O2 is answered — the join is permitted — but it stays out of v1 (§3.3). |
| D10 | **No adverse-event classification in v1.** | Noted in the methodology statement as a scope limit, once, in the appendix. See the risk in §8. |
| D11 | **Internal tool, client-deliverable output.** | Vi staff run it. The report is built to be handed to a client as-is: provenance appendix, methodology statement, visible confidence tiers. Nothing ships externally before the legal question in O1 is answered. |
| D12 | **Vendored fork.** | `vsm/mining` and `vsm/llm` are copies. Parent is not modified. Gold-list drift accepted. |
| D13 | **No forecasts and no accuracy claims in v1.** | We report *measured* movement between snapshots. We do not predict, and we do not quote an accuracy figure, because we have not backtested one. Enforced by G5. |

### What does not come across

The public HCP site · consent ledger · GPC · first-party collector · CSP/nonce
machinery · admin console · analytics · the rung ladder · the 19 clinical QA
checks · Tier-C hard blocking and robots gating (D5) · pocket-guide PDF ·
newsletter · **the educational-content path from revision 1 (D7)**.

## 3. Architecture

```
vi-signal-mine/
  vsm/
    config.py                Settings; mode switches; offline master switch
    app.py                   composition root (FastAPI)
    mining/                  ── VENDORED from engine/mining ──
      budget client denylist discover miner queries recency robots
      serp signals store tiers unlocker venues
    llm/
      client.py              vendored, generalised (§3.2)
      progress.py            vendored: run-keyed progress registry
      prompts.py             NEW
      schema.py              NEW
    topics/
      model.py               Topic: brief, competitor set, venue routing
      store.py               topics + their snapshot series
    runs/
      model.py               Run, RunMode, topic_id, parent_id, artifact paths
      store.py               SQLite metadata + var/runs/<id>/ artifacts
    analysis/                ── the transformation layer, rungs 4-7 ──
      resolve.py             mention → entity, against the topic lexicon
      corroborate.py         independence test + confidence tier
      cluster.py             themes; theme naming; venue mix
      stance.py              stance per theme, per venue class
      authorclass.py         signal → author class + basis. The v2 seam (§3.3)
      duallens.py            HCP-venue view vs patient-venue view, and the gap
      momentum.py            snapshot deltas; null with a reason when N=1
      anomaly.py             this snapshot vs the topic's rolling baseline
    modes/
      mine.py insight.py report.py
    guards/
      cost.py citations.py advisory.py corroboration.py claims.py terms.py
    ui/
      app.py templates/ static/
  tests/
  var/                       runs + db (gitignored)
```

`analysis/` is the part that does not exist in the parent, and it is the part
that matters. The research finding was that collection is a line item and the
transformation layer is the product; this directory is that finding expressed as
a package boundary. Each module is independently testable on a fixture signal
set with no network and no model.

### 3.1 What is vendored, and what changes on the way in

`engine/mining/` copies to `vsm/mining/` with its import prefix rewritten. It is
already self-contained — its own docstring records that the local query-shape
fallback exists *"only so this package never has to import the orchestrator."*

The pieces that carry weight:

- **`venues.py`** — the gold list. A hand-checked venue registry routed by
  therapeutic area, covering evidence, guideline bodies by specialty,
  regulatory, HCP discussion and patient communities. Every domain verified
  2026-08-02 by a plain `httpx` GET of its `robots.txt`; three unreachable
  candidates were dropped rather than listed on faith. **This file is also the
  substrate for D9** — its `kind` field is what makes author class computable
  without identity resolution. Not to be regenerated from memory.
- **`queries.py`** — gold-scoped planning. `site:` chains first, open web only
  as a tail.
- **`denylist.py`** — brand and pharma-corporate sites, content farms,
  pay-to-publish, repository duplicates. Every drop records its reason, because
  a silent filter is indistinguishable from finding nothing.
- **`recency.py`** — a 90-day window on discussion and community venues, never
  on evidence or guidelines where the test is current edition, not recent date.
- **`signals.py`** — one hit → one normalised row. Three rules live inside it:
  `author_type` is never inferred from a username; patient-forum signal is
  themes only, with no author identifier of any kind, not even hashed; and no
  provenance means not admissible.
- **`budget.py` · `serp.py` · `discover.py` · `unlocker.py` · `client.py` ·
  `store.py` · `robots.py` · `miner.py` · `tiers.py`** — the sweep layer and the
  three Bright Data surfaces, each over an injectable transport, which is how
  the whole package tests with zero network and no key.

Changed on the way in:

- `tiers.assert_collectable` no longer raises; call sites record the tier and
  proceed (D5). Refusal code stays behind a default-off flag.
- `RobotsCache` still fetches and reports; its answer no longer vetoes (D5), and
  is written to coverage.
- `signals.build_row` gains `topic_id` and `snapshot_at`, and keeps every
  existing key byte-compatible so the parent's fixtures serve as parity tests.

### 3.2 The LLM layer

Most of `engine/llm/client.py` is machinery worth keeping verbatim: our own retry
loop (the SDK's `max_retries=2` billed retried-away attempts invisibly, so three
generations could log as one — or as $0.00 on the failure paths), per-attempt
metering, budget re-check between attempts, spend accounting, streaming, and the
prompt-cache prefix check.

What changes: the parent bakes in two output schemas and two entry points. This
fork needs one per analysis pass, so `draft` and `_stream_article` are replaced
by `complete_structured(*, system, user, schema, max_output_tokens, on_progress)`
— same loop, schema and prompts injected. `plan_queries` is kept as-is; it is
exactly what MINE's lexicon step needs.

`prompts.py` keeps the cache discipline: **the system prompt must be
byte-identical across runs.** Interpolating a topic or a term list into the
prefix makes it unique per run and throws the cache away. Run-specific content
goes in the user message.

**Where the model is and is not used.** The model reads text, proposes clusters,
names themes, classifies stance, and writes prose. It does **not** compute
counts, deltas, confidence tiers, momentum, or anomaly thresholds — those are
arithmetic in `analysis/`, because a number a model produced is a number nobody
can reproduce. The division is the same one the parent draws when it lets the
model contribute query *strings* while routing stays deterministic.

### 3.3 The author-resolution seam

O2 is answered: the social-handle → NPI join is permitted. It is still not in
v1, because it is a data-engineering problem against Provider360 and the Pipl
bridge, not a feature of this UI, and building it inside a UI project is how it
would get done badly. What v1 owes it is a seam it can drop into.

`analysis/authorclass.py` is the only place any pass may learn who is speaking:

```
resolve_author_class(signal, resolver) -> AuthorClass(value, basis, confidence)
```

- **v1 resolver** — venue-derived, from the registry's `kind`.
  `basis="venue"`. Says a post came from an HCP-discussion venue.
- **v2 resolver** — identity-derived, handle → NPI. `basis="identity"`, and
  carries the NPI. Says a named clinician wrote it.

Two rules make the seam worth having.

**Every consumer reads `value` and `basis`, and may assume neither.** `stance.py`
and `duallens.py` take an `AuthorClass`, never a venue. Swapping the resolver
therefore changes no code downstream — which is the entire point, and is what a
test asserts by running both passes against a stub identity resolver.

**The basis travels into the report, always.** "HCP" from a venue and "HCP" from
an NPI are different claims, and a report that prints them identically is
lying about the stronger one. `methodology.md` states which resolver ran.
Collapsing the two would be the same category of error as the parent's
`resolved=False` stamp on every model-returned reference — a trust state the
producer is not entitled to assert.

Nothing else in v1 changes. The seam costs one module and one dataclass.

## 4. The three modes

### 4.1 MINE — collect a snapshot

**Topic brief:** brand or product · INN / molecule (generic names) · therapeutic
area · competitor set · the questions we care about · spend band.

**Spend band** is one of three presets — `probe`, `standard`, `deep` — each
fixing `queries_per_cluster`, `serp_results_per_query`,
`discover_results_per_cluster` and `page_fetches_per_cluster`. A preset rather
than a dollar figure because those four knobs interact and a dollar target gives
no guidance on which to move. Each band shows its estimated cost on the form.

1. **Lexicon** — Claude expands the topic into clusters and query strings.
2. **Plan** — `queries.plan_queries` orders the sweep: gold-scoped `site:`
   queries against the venues the registry rates for this cluster's therapeutic
   areas, then one Discover job per cluster, then open-web queries as a **tail**
   that runs only if the gold list under-delivers.
3. **Sweep** — SERP → Discover → Unlocker fetch → normalise → dedupe, under a
   result cap and a cost ledger.

The model contributes query strings only. Gold routing, `site:` scoping, spend
bands and the recency split stay deterministic — which is what makes an offline
dry run rehearse the live sweep query-for-query, asserted by a parity test.

Because open-web queries are last, a sweep that stops early has executed a
*prefix* of the plan. That keeps the offline rehearsal honest even when the live
run spends less than the plan allowed.

**Cost shape:** SERP $0.0015/request; a successful Unlocker page fetch $0.03 —
twenty times more. That ratio is the whole argument for gold-first. A real
Stage-2 sweep in the parent cost $0.0315.

→ `signals.jsonl` · `provenance.json` · `coverage.json` · `cost.json` · `plan.json`

### 4.2 INSIGHT — turn a snapshot into findings

Input: one snapshot, plus the topic's earlier snapshots for the delta passes.
Seven passes, each its own artifact, each re-runnable alone.

| Pass | Artifact | What it does |
|---|---|---|
| **Resolve** | `entities.json` | Mention → entity against the topic lexicon, so "Symproic", "naldemedine" and "that OIC drug" collapse to one node. Rung 2. |
| **Corroborate** | `findings.json` | Groups claims and assigns a confidence tier. Rung 4 — see below. |
| **Cluster** | `themes.json` | Themes with volume, venue mix, and **evidence strength derived from the registry's venue `kind`** — a property of where a theme was found, not a judgement of its merit. Computed, not modelled. |
| **Stance** | `stance.json` | Stance per theme **per venue class**, never blended. |
| **Dual-lens** | `duallens.json` | The same theme seen from HCP venues vs patient communities, ranked by divergence. |
| **Momentum** | `momentum.json` | Per theme, versus the topic's prior snapshots: volume delta, venue-mix shift, stance shift. |
| **Anomaly** | `anomaly.json` | This snapshot against the topic's rolling baseline — the median of its previous three snapshots, or of all of them when fewer than three exist. Median rather than mean so one unusual week does not redefine normal. |

**Corroboration, and what "independent" means.** Tastewise's published rule is
that three independent sources must align before a finding is high-confidence.
We adopt it with our own definition: two sources are independent when they sit
on **different registrable domains** *and* **different venues**. Syndicated
copies of one press release are one source, not five.

| Tier | Test | Where it may appear |
|---|---|---|
| `corroborated` | ≥3 independent sources | Report main body |
| `emerging` | 2 independent sources | Report, in a separately labelled section |
| `single-source` | 1 | Ledger only — never promoted |

Enforced by G6, not by prompt.

**Stance is split by venue class and never aggregated.** Given that only 2–5% of
disease-area conversation comes from clinicians
([CREATION.co](https://creation.co/knowledge/if-you-already-have-a-healthcare-social-listening-tool-why-implement-another-one/)),
an unsplit disease-area sentiment score is a patient sentiment score wearing a
clinical label. `stance.json` has no field for a blended number.

Note that `signals.build_row` deliberately leaves `sentiment` as `None` — the
parent runs no classifier and refuses to invent one. The stance pass is this
fork's classifier, and it writes to its own artifact rather than back-filling the
signal row, so a signal row still says only what collection witnessed.

**The dual-lens gap is the headline output.** For each theme, the HCP-venue view
and the patient-community view, and the delta between them. Nobody asks for the
gap, and it is the most actionable thing on the page — a theme clinicians are
neutral on and patients are angry about is a different problem from the reverse,
and neither is visible in a blended number.

**Momentum is measured, never predicted.** It reports the delta between dated
snapshots. It carries no forecast and no accuracy figure (D13, G5). Black Swan
and Spate publish forecast accuracy because they backtest monthly; until Vi does
the same, a prediction here would be a number with nothing behind it.

**Anomaly detection is arithmetic; the description is model-written.** Thresholds
over the deltas find what changed — a theme that appeared, one that vanished, a
venue that went quiet, a stance flip, a volume spike. The model then writes what
that means. Detection must be reproducible; narration need not be.

### 4.3 REPORT — package for a client

| Artifact | What it is |
|---|---|
| `pulse_report.md` | The read: what is being said, where, by which kind of source, moving which way, and what changed. Findings carry their confidence tier visibly. |
| `provenance_appendix.md` | Every claim → `signal_id` → URL, venue, venue class, capture timestamp, collection method. The clickable traceback. |
| `methodology.md` | What was searched, where, when, what was excluded and why, how confidence tiers are defined, and the scope limits. |
| `worth_considering.md` | Options worth weighing. Suggestions, never decisions (G2). |

`methodology.md` is not boilerplate. EMA GVP Module VI accepts digital sources
for pharmacovigilance *"as long as social listening and monitoring methods are
systematic, well-documented, and verifiable"* — this artifact is what makes that
claim checkable, and it is the reason the provenance discipline inherited from
the parent is a feature rather than overhead. It states the D10 scope limit
**once**: the output is not screened for adverse events and is not a
pharmacovigilance input.

## 5. Guards — rules that are code, not prompt text

The parent's hardest-won lesson: a rule stated only in a prompt is an
optimisation, never a control. Each guard gets direct tests.

**G1 — The model may not author trust state.** `citations.py` binds
`signal_id → URL · venue · captured_at` from the ledger. A model-emitted citation
is discarded, not trusted. A claim with no bindable `signal_id` blocks the
report. This exists because of a specific near-miss in the parent: its
scaffolding path used to mint PMIDs as `30000000 + (seed % 9999999)` with a
matching PubMed URL — plausible enough to survive review, which is exactly what
made it dangerous.

**G2 — Suggestions, never decisions.** `advisory.py` rejects directive
constructions in `worth_considering.md` — "you should", "you must", "we
recommend that you", "the right move is". The banned list in `prompts.py` must
equal the one in `advisory.py`; a test pins the equality, because otherwise the
model is told a different rule than the one that rejects it.

**G3 — Cost binds before spend.** Estimate shown and confirmed before any live
call. `VSM_RUN_COST_CAP_USD` binds per run; the default sits near a realistic run
with headroom, because a cap that can never bind caps nothing. A breach stops the
sweep **cleanly** — partial rows, recorded deferral, no exception thrown at the
pipeline. The Bright Data account is shared with other Vi projects, so caps are
tight on purpose; raise per run, knowingly, never by editing the default.

**G4 — Optional never-say terms.** `terms.py` takes a per-run list of terms the
output may never contain, empty by default and a no-op when empty. Not a required
guardrail, but a pharma operator will want it for brand names.

**G5 — No unmeasured claims.** `claims.py` rejects forecast and accuracy language
anywhere in the report — "will grow", "expected to reach", "projected", "% accurate",
"predicts". D13. This is the honest counterpart to the market's rung 9: vendors
who publish accuracy earned it by backtesting. Until Vi backtests, the report
describes measured movement and stops there.

**G6 — Corroboration gate.** A finding below `corroborated` cannot appear in the
report's main body; `emerging` goes to a labelled section; `single-source` never
leaves the ledger.

### The switches

```
VSM_MINER   = auto | fake | live      fake = deterministic even when online
VSM_DRAFTER = auto | llm              auto = model when a key is set
VSM_OFFLINE = 1                        master switch, wins over both
```

`VSM_OFFLINE` winning over both is what stops a stray key in a shell from
pointing the test suite at a live API. `fake` exists so the analysis passes can
be demonstrated without paying for mining. **Live-without-a-key raises rather
than falling back** — a run that quietly stopped collecting and served
deterministic rows looks identical to one that collected.

## 6. UI

Local FastAPI + Jinja. No build step, no CDN, no external font — the parent's
rule, and it means the tool works on a plane. Templates use `StrictUndefined`,
so write `{% if foo is defined and foo %}`.

1. **Topics** — the home screen. Each topic as a card: last snapshot, how many
   snapshots, spend to date, and a sparkline of volume across snapshots. "New
   snapshot" and "New topic".
2. **Topic brief** — create or edit a topic. Live cost estimate as the spend band
   moves.
3. **Confirm spend** — explicit interstitial before any live call: estimate, cap,
   what will be spent where.
4. **Run stream** — stage timeline, live progress, running cost, fed by the
   run-keyed progress registry.
5. **Snapshot** — the signals table with filters by venue, venue class, date,
   confidence tier.
6. **Insight** — the seven views. The dual-lens gap leads, because it is the
   output nobody thinks to ask for. Momentum and anomaly show `no prior
   snapshot` plainly on a topic's first run rather than an empty chart.
7. **Report** — preview with **every claim's citation clickable through to its
   source row and URL**. This is the visible half of G1.
8. **Exports** — any artifact.

Design work runs through the `impeccable` skill.

## 7. Testing

TDD throughout. Hermetic by default: `VSM_OFFLINE=1`, `httpx.MockTransport` for
all three Bright Data surfaces, an injected Anthropic client over a mock
transport for the model. The parent tests its whole mining package with zero
network and no key; that harness travels intact.

`analysis/` is pure functions over a fixture signal set — no network, no model
for the arithmetic passes — so corroboration, momentum and anomaly are testable
with hand-built inputs and exact expected outputs.

Tests that carry weight:

- **Parity** — `vsm/mining` issues the same queries in the same order as the
  parent for the same cluster, against the parent's own fixtures. Proves the
  vendoring did not quietly change behaviour.
- **Independence** — five syndicated copies of one press release count as **one**
  source, not five, and therefore do not reach `corroborated`.
- **First snapshot** — momentum and anomaly return `null` with reason
  `no prior snapshot`; nothing fabricates a trend.
- **G1** — an unbound claim blocks the report; a model-emitted citation is
  discarded.
- **G2** — directive language rejected; the two banned lists are equal.
- **G3** — a cap breach yields partial rows and a recorded deferral, not an
  exception; live-without-a-key raises.
- **G5** — forecast and accuracy language rejected anywhere in the report.
- **G6** — a `single-source` finding cannot reach the report body.
- **Stance** — no code path produces a venue-class-blended stance number.
- **Author seam** — stance and dual-lens produce identical structure under a
  stub identity resolver as under the venue resolver, and the recorded `basis`
  differs. Proves §3.3 is a seam and not a comment.
- **Offline switch** — with `VSM_OFFLINE=1` and both keys present in the
  environment, no outbound call is attempted anywhere.
- **Chaining** — a report resolves back through its runs to the exact signal
  rows it cites.

## 8. Known risk, accepted

**D10 + D11 interact.** The report is built to be handed to a client, and v1 does
not classify adverse events. A post describing a suspected adverse reaction can
therefore reach a client inside a themes table with nothing marking it, and
under EMA GVP Module VI the marketing authorisation holder's obligation attaches
whether or not anything flagged it.

The owner's decision, taken knowingly on 2026-08-25. Mitigation in v1 is the
single scope statement in `methodology.md` and nothing more. The cheapest way to
close it later is a classifier pass in `analysis/` that tags candidates and
routes them to a named human — detect, label, route, record; **never file.** The
parent's rule that the engine never posts generalises directly: the engine never
files.

## 9. Build order

1. Skeleton, config, topic + run stores, error types
2. Vendored mining + the parity test
3. MINE end to end on the fake miner
4. `analysis/` — resolve, corroborate, cluster, stance (pure, fixture-driven)
5. `analysis/` — dual-lens, momentum, anomaly (needs a two-snapshot fixture)
6. REPORT + guards G1/G2/G5/G6
7. UI (via `impeccable`)
8. One live smoke run with real keys — cost recorded
9. GitHub repo created and pushed

## 10. Open questions for a human

- **O1** Does surfacing a suspected adverse event to a Vi client, from public
  data Vi collected, place any duty on **Vi**, or only on the marketing
  authorisation holder? Legal, not product. Gates D11 client delivery. Related
  to the parent's open item O3.
- **O2 — ANSWERED 2026-08-25: yes, the join is permitted.** The owner confirmed
  that a social-handle → NPI join is allowed under the licences covering
  Provider360 and the Pipl NPI↔HEM bridge. This is the moat the research
  identified — CREATION.co built 3M+ verified HCP profiles to do what Vi's
  7.24M-HCP graph could do better. It is **deliberately not in v1**; §3.3 is the
  seam that keeps it a drop-in rather than a rewrite. Scope it as its own piece
  of work.
- **O3** Does the gold list need re-verification before the first live run? It
  was checked 2026-08-02; robots answers and venue availability drift.
- **O4** With D5 in force, does Vi need an internal aggregate record of hosts
  collected against their stated preference? Coverage captures it per run;
  whether it needs to roll up is not a code question.
- **O5** Should the parent eventually consume `vsm/mining` rather than its own
  copy? Deferred by D12; revisit only if the gold list starts changing often.
