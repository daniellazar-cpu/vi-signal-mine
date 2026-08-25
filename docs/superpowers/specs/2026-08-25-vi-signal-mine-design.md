# Vi Signal Mine — design

**Date:** 2026-08-25
**Status:** approved for planning
**Owner:** Daniel Lazar
**Parent:** `daniellazar-cpu/attending-health-engine` (local: `~/Documents/forum-engine`)

---

## 1. What this is

A local-first tool that mines the public web for healthcare/pharma signal, turns
that signal into insight, and turns insight into cited content. It is a fork of
the social-listening and content-curation mechanism inside the Attending Health
Forum Engine, extracted so that anyone can run it themselves against their own
brief without the surrounding publishing property.

Three modes. Any one runs alone; each can consume the previous one's output.

```
MINE ──▶ INSIGHT ──▶ CONTENT
 │         │            │
 │         │            └─ findings report · educational brief
 │         │               engagement drafts · worth considering
 │         └─ themes · gaps · stance · ledger + coverage
 └─ normalised, deduped signal rows + provenance + cost
```

## 2. Decisions on record

Every one of these was decided with the owner on 2026-08-25. They are recorded
here because several of them close off options that a future reader would
otherwise reopen.

| # | Decision | Consequence |
|---|---|---|
| D1 | **Healthcare/pharma only.** Not domain-agnostic. | The gold-list venue registry, therapeutic-area routing and medical query shapes travel unchanged. No pluggable topic packs. |
| D2 | **Three chainable modes**, not per-stage start/stop. | Simpler UI, three clear cost profiles. A run records its upstream run. |
| D3 | **Local-first, no auth.** | Runs on the operator's machine. Own keys via `.env`. No user table, no login, no multi-tenancy, no hosted deployment. |
| D4 | **Cost caps and the budget ledger travel.** | Estimate-before-spend, per-run USD cap, clean stop on breach. |
| D5 | **Tier-C blocklist and live robots.txt gating do NOT travel.** Raised as a concern, reaffirmed by the owner. | The miner will collect from any host the search returns. Robots state is still *recorded* per host in the coverage artifact, because D7 asks for keep/drop reasons — reporting, not gating. |
| D6 | **The rung 0–5 claim ladder and the 19 clinical QA checks do not travel.** | Output is a cited findings report for a commercial reader, not a promotional asset needing claim classification. |
| D7 | **INSIGHT produces all four outputs**: themes/clusters, questions & unmet needs, sentiment/stance, source ledger + coverage. | Four independent passes, four artifacts. |
| D8 | **CONTENT produces four artifacts**, per the owner's own wording: a findings report with citations and full traceback; an educational output curated for customers; engagement drafts; and "things worth considering — always suggestions, not decision-making for them". | Rule G2 below makes the last clause structural. |
| D9 | **Educational brief reader = Vi's pharma / life-science clients** (commercial and medical affairs). | Register is business-to-business briefing, not clinical education. |
| D10 | **Vendored fork (approach A).** | `vsm/mining` and `vsm/llm` are copies. The parent is not modified and takes no dependency on this repo. Gold-list drift is accepted. |

### What does not come across

The public HCP site · the consent ledger and GPC publication · the first-party
event collector · the CSP/nonce machinery · the admin console · analytics · the
rung ladder · the 19 clinical QA checks · Tier-C hard blocking and robots gating
(D5) · pocket-guide PDF packaging · the newsletter edition.

The last two are the only reversible omissions: the parent's packaging path is
intact and could be ported later if a PDF or email edition is wanted out of a
findings report.

## 3. Architecture

```
vi-signal-mine/
  README.md
  CLAUDE.md                      repo instructions
  .env.example                    keys, zones, caps, switches
  pyproject.toml
  vsm/
    config.py                     Settings; mode switches; the offline master switch
    app.py                        composition root (FastAPI)
    errors.py                     ContractViolation and friends
    mining/                       ── VENDORED, essentially unchanged ──
      budget.py client.py denylist.py discover.py miner.py queries.py
      recency.py robots.py serp.py signals.py store.py tiers.py
      unlocker.py venues.py
    llm/
      client.py                   vendored, generalised (see §3.2)
      progress.py                 vendored: run-keyed progress registry
      prompts.py                  NEW: lexicon · themes · gaps · stance
                                       report · brief · drafts · suggestions
      schema.py                   NEW: typed model outputs, one per pass
    runs/
      model.py                    Run, RunMode, artifact paths, parent linkage
      store.py                    SQLite metadata + var/runs/<id>/ artifacts
      registry.py                 list · read · resume
    modes/
      mine.py                     brief → lexicon → plan → sweep → signals
      insight.py                  signals → themes · gaps · stance · ledger
      content.py                  insight → report · brief · drafts · suggestions
    guards/
      cost.py                     estimate, cap, clean stop
      citations.py                bind every claim to a signal_id
      advisory.py                 reject directive language in suggestions
      terms.py                    optional per-run never-say list
    ui/
      app.py  templates/  static/
  tests/
  var/                            runs + db (gitignored)
```

### 3.1 What is vendored, and why unchanged

`engine/mining/` copies over as `vsm/mining/` with only its import prefix
rewritten. It is already a self-contained package — its own docstring records
that the local query-shape fallback exists *"only so this package never has to
import the orchestrator"*. It carries:

- **`venues.py`** — the gold list. A hand-checked venue registry routed by
  therapeutic area: evidence, guideline bodies by specialty, regulatory, HCP
  discussion, patient communities. Every domain was verified on 2026-08-02 by a
  plain `httpx` GET of its `robots.txt`; three candidates that could not be
  reached were dropped rather than listed on faith. This file is the single most
  valuable thing being forked and it is not to be regenerated from memory.
- **`queries.py`** — gold-scoped query planning. `site:` chains against the gold
  list first, open web only as a tail.
- **`denylist.py`** — what is not worth paying for: brand and pharma-corporate
  sites, content farms, pay-to-publish publishers, repository duplicates. Every
  drop records its reason, because a silent filter is indistinguishable from
  finding nothing.
- **`recency.py`** — a 90-day-plus window applied to discussion and community
  venues and never to evidence or guidelines, where the test is current edition
  rather than recent date.
- **`budget.py`** — free-tier accounting and per-call cost constants.
- **`signals.py`** — one hit → one normalised row. Three rules live inside it
  rather than in callers: `author_type` is never inferred from a username;
  patient-forum signal is themes only, with no author identifier of any kind,
  not even hashed; and no provenance means not admissible.
- **`serp.py` · `discover.py` · `unlocker.py` · `client.py`** — the three Bright
  Data surfaces over one HTTP client. Each takes an injectable transport, which
  is how the whole package tests with zero network and no API key.
- **`tiers.py`** — venue tier classification. **Retained for its
  classification and `domain_of`/`registrable_domain` helpers; the Tier-C
  refusal path is disabled per D5.** The tier value still lands on every row so
  a reader can see what a host is, and re-enabling the gate is a one-line
  change if that decision is ever revisited.
- **`store.py` · `robots.py` · `miner.py`** — the sweep run layer.

**Changed on the way in:**

- `tiers.assert_collectable` no longer raises; the three call sites that
  enforced it (parser, `UnlockerClient.fetch`, run layer) record the tier and
  proceed (D5). The refusal code stays in place behind a config flag defaulting
  to off, so the decision is reversible without archaeology.
- `RobotsCache` still fetches and still reports; its answer no longer vetoes a
  fetch (D5). The answer is written to the coverage artifact.
- `signals.build_row` gains `run_id` alongside `campaign_id` (same value,
  clearer name) and keeps every other key byte-compatible, so the parent's
  fixtures remain usable as parity tests.

### 3.2 The LLM layer

`engine/llm/client.py` is 1,292 lines, and most of it is machinery worth keeping
verbatim: our own retry loop (the SDK's `max_retries=2` billed retried-away
attempts invisibly, so three generations could log as one — or as $0.00 on the
failure paths), per-attempt metering, budget re-check between attempts, spend
accounting, streaming with partial-output extraction, and the prompt-cache
prefix check.

What changes: the parent hard-codes two output schemas (`_article_schema`,
`_query_plan_schema`) and two entry points (`draft`, `plan_queries`). This fork
needs seven distinct structured outputs, so:

- `plan_queries` is kept as-is — it is exactly what MINE's lexicon step needs.
- `draft` and `_stream_article` are replaced by
  `complete_structured(*, system, user, schema, max_output_tokens, on_progress)`
  — the same retry/meter/budget/stream loop, with the schema and prompt pair
  passed in rather than baked in.
- `prompts.py` keeps the parent's cache discipline: **the system prompt must be
  byte-identical across runs**, so nothing run-specific may be interpolated into
  it. Interpolating a brief or a term list into the system prefix makes it unique
  per run and throws the cache away. Run-specific content goes in the user
  message.

### 3.3 Runs and chaining

A run is `(id, mode, parent_id, brief, status, created_at, cost_usd)` in SQLite,
with artifacts on disk at `var/runs/<id>/`.

```
POST /run  {mode: mine,    brief: {...}}          → m_a1b2c3
POST /run  {mode: insight, from: m_a1b2c3}        → i_d4e5f6
POST /run  {mode: content, from: i_d4e5f6}        → c_g7h8i9
```

`parent_id` is what makes a chain inspectable: from any content run you can walk
back to the exact signal rows it was built from. There is also a "run all three"
path that creates three linked runs rather than one composite run, so a failure
partway leaves the completed upstream work usable.

An INSIGHT run may alternatively take an uploaded `signals.jsonl` instead of a
parent id, for signal collected elsewhere.

## 4. The three modes

### 4.1 MINE

**Brief:** topic · INN / molecule (generic names) · therapeutic area ·
competitor set · the questions the operator cares about · spend band.

**Spend band** is one of three named presets — `probe`, `standard`, `deep` —
each fixing `queries_per_cluster`, `serp_results_per_query`,
`discover_results_per_cluster` and `page_fetches_per_cluster`. It is a preset
rather than a free-text dollar figure because those four knobs interact, and a
user who sets a dollar target has no way to know which of them to move. The
estimated cost of each band is shown next to it on the brief form.

1. **Lexicon** — Claude expands the brief into clusters and query strings.
2. **Plan** — `queries.plan_queries` turns each cluster into an ordered plan:
   gold-scoped `site:` queries against the venues the registry says are strong
   for this cluster's therapeutic areas, then one Discover job per cluster, then
   open-web queries as a *tail* that only runs if the gold list under-delivers.
3. **Sweep** — SERP → Discover → Unlocker page fetch → normalise → dedupe,
   under a result cap and a cost ledger.

**The model contributes query strings only.** Gold-list routing, `site:`
scoping, spend bands and the recency split stay deterministic in `queries.py`.
This is the parent's rule and the reason an offline dry run rehearses the live
sweep query-for-query — asserted by a parity test, not assumed.

Because the open-web queries are last, a sweep that stops early has executed a
*prefix* of the plan, which is what keeps the offline rehearsal honest even when
the live run spends less than the plan allowed.

**Cost shape:** a SERP request is $0.0015; a successful Unlocker page fetch is
$0.03 — twenty times more. That ratio is the entire argument for gold-first, and
a real Stage-2 sweep in the parent cost $0.0315.

**Artifacts:** `signals.jsonl` · `provenance.json` · `coverage.json` ·
`cost.json` · `plan.json`

### 4.2 INSIGHT

Input: a MINE run id, or an uploaded signal set. Four independent passes, each
its own artifact, each re-runnable without redoing the others.

| Pass | Artifact | What it holds |
|---|---|---|
| Themes | `themes.json` | Clusters of what is actually being discussed, with volume, venue mix and evidence strength per theme. **Evidence strength is a property of the venues a theme was found in, not a judgement of the theme's clinical merit** — a theme carried by guideline bodies and evidence venues scores higher than one carried only by discussion venues. It is derived from the venue registry's `kind`, so it is computed, not modelled. |
| Gaps | `gaps.json` | Questions being asked in the signal that the signal set does not answer — the content gaps |
| Stance | `stance.json` | Sentiment and stance per theme, **split by venue class** — guideline body, evidence, HCP discussion, patient community |
| Ledger | `ledger.csv` + `coverage.json` | Every collected row with URL, venue, tier, date, cost and keep/drop reason including what robots said; plus which venues answered and which came back empty |

**Stance is split by venue class and never aggregated across classes.** A single
sentiment number spanning a guideline body and a patient forum describes nothing
that exists. The artifact has no field for a blended score.

Note that `signals.build_row` deliberately leaves `sentiment` as `None` — the
parent runs no classifier and refuses to invent one. The stance pass is this
fork's classifier, and it writes to its own artifact rather than back-filling the
signal row, so a signal row still says only what collection witnessed.

### 4.3 CONTENT

Input: an INSIGHT run id.

| Artifact | What it is |
|---|---|
| `findings_report.md` | The primary output. What was found, with citations, links and full traceback to the collected rows. |
| `educational_brief.md` | Curated for a pharma commercial / medical-affairs reader (D9): what the signal means for their programme. |
| `engagement_drafts.json` | Short social drafts to a queue. **The engine never posts** — a named human does. |
| `worth_considering.md` | Options worth weighing, framed as suggestions. |

## 5. Guards — rules that are code, not prompt text

The parent's hardest-won lesson is that a rule stated only in a prompt is an
optimisation, never a control. Three guards, each with direct tests.

### G1 — The model may not author trust state

`guards/citations.py` binds `signal_id → URL · venue · captured_at` **from the
ledger**. A citation emitted by the model is discarded, not trusted. A claim
carrying no bindable `signal_id` **blocks the report**.

This exists because of a specific near-miss in the parent: its scaffolding path
used to mint PMIDs as `30000000 + (seed % 9999999)` with a matching PubMed URL —
plausible enough to survive review, which is exactly what made it the most
dangerous thing in the pipeline. The parent's fix was to stamp `resolved=False`
on every reference regardless of what the model returned. Same discipline here:
the model proposes a claim, the pipeline binds the source, and an unbound claim
does not ship.

### G2 — Suggestions, never decisions

`guards/advisory.py` runs over `worth_considering.md` and
`engagement_drafts.json` and rejects directive constructions — "you should", "you
must", "we recommend that you", "the right move is", "the best option is".

The owner's framing (D8): *"always suggestions not a decision making for them."*
The prompt says this too; treat that as an optimisation. The check is the
control, and it runs on model output the same way the parent's never-say check
does.

The banned-construction list in `prompts.py` must equal the one in
`advisory.py`. A test pins the equality — if they drift, the model is being told
a different rule than the one that rejects it.

### G3 — Cost binds before spend

- A cost estimate is computed and **shown and confirmed** before any live call.
- `VSM_RUN_COST_CAP_USD` binds per run. Following the parent's reasoning: a cap
  that can never bind caps nothing, so the default is set near a realistic run
  (~$0.03 mining + ~$1 model) with headroom, not at 25×.
- A breach stops the sweep **cleanly** — partial rows, a recorded deferral, no
  overspend, and no exception thrown at the pipeline.
- The Bright Data account is shared with other Vi projects, so the caps are
  tight on purpose. Raise them per run, knowingly, never by editing the default.

### The switches

```
VSM_MINER   = auto | fake | live      fake = deterministic even when online
VSM_DRAFTER = auto | llm              auto = model when a key is set
VSM_OFFLINE = 1                        master switch, wins over both
```

`VSM_OFFLINE` winning over both is what stops a stray key in a developer's shell
from pointing the whole test suite at a live API. `fake` exists so the insight
and content passes can be demonstrated without also paying for mining.

**Live-without-a-key raises rather than falling back.** A run that quietly
stopped collecting and served deterministic rows looks identical to one that
collected. Carried from the parent; do not soften it into a default.

### G4 — Optional never-say terms

`guards/terms.py` takes a per-run list of terms the generated output may never
contain, **empty by default**. Not selected as a required guardrail, but it
costs nothing to provide and a pharma operator will want it for brand names.
When the list is empty the check is a no-op.

## 6. UI

Local FastAPI + Jinja. No build step, no CDN, no external font — the parent's
rule, and it means the tool works on a plane. Templates use `StrictUndefined`,
so `{% if foo %}` on an undefined variable 500s the page; write
`{% if foo is defined and foo %}`.

Six screens:

1. **Home** — three mode cards. Each offers *start fresh* or *continue from
   run…*. Below them, a recent-runs table: id, mode, parent, status, cost, when.
2. **Brief** — the MINE form, with a live cost estimate that updates as the
   spend band moves.
3. **Confirm spend** — an explicit interstitial before any live call, showing
   the estimate, the cap, and what will be spent where.
4. **Run stream** — a stage timeline with live progress and a running cost
   counter, fed by the run-keyed progress registry.
5. **Results** — mode-appropriate. Signals table with filters for MINE; the four
   insight views for INSIGHT; for CONTENT, a preview where **every claim's
   citation is clickable through to its source row and URL** (this is the visible
   half of G1 — traceback the owner can actually click).
6. **Exports** — download any artifact.

Design work runs through the `impeccable` skill.

## 7. Testing

TDD throughout. Hermetic by default: `VSM_OFFLINE=1`, `httpx.MockTransport` for
all three Bright Data surfaces, an injected Anthropic client over a mock
transport for the model. The parent tests its entire mining package with zero
network and no key, and that harness travels intact.

Tests that carry real weight:

- **Parity** — `vsm/mining` issues the same queries in the same order as the
  parent for the same cluster, checked against the parent's own fixtures. This
  is what proves the vendoring did not quietly change behaviour.
- **G1** — a claim with no bindable `signal_id` blocks the report; a
  model-emitted citation is discarded rather than trusted.
- **G2** — directive language is rejected; `prompts.py`'s banned list equals
  `advisory.py`'s.
- **G3** — a cap breach yields partial rows and a recorded deferral, not an
  exception; live-without-a-key raises.
- **Offline master switch** — with `VSM_OFFLINE=1` and both keys set in the
  environment, no outbound call is attempted anywhere.
- **Chaining** — a content run resolves back through its parents to the exact
  signal rows it cites.

## 8. Build order

1. Skeleton, config, run store, error types
2. Vendored mining + the parity test
3. MINE end to end on the fake miner
4. INSIGHT's four passes
5. CONTENT's four artifacts + guards G1/G2/G4
6. UI (via `impeccable`)
7. One live smoke run with real keys — cost recorded
8. GitHub repo created and pushed

## 9. Open questions for a human

- **O1** Does the gold list need re-verification before the first live run? It
  was checked 2026-08-02; robots.txt answers and venue availability drift.
- **O2** With D5 in force, is there an internal record needed of which hosts
  were collected against their stated preference? The coverage artifact captures
  it per run; whether that needs to aggregate anywhere is not a code question.
- **O3** Should the parent eventually consume `vsm/mining` instead of its own
  copy? Deferred by D10; worth revisiting only if the gold list starts changing
  often.
