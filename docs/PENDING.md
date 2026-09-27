# Pending - to productionize Bright Data and make the site fully functional

Status as of 28 September 2026. **Production collects live.** A probe sweep on
the deployment ran against the real Bright Data API in 8 seconds and returned 15
real rows from 6 sites; INSIGHT and REPORT ran on it. What is still open is below.

---

## A. Keys and environment

Set on production (`vi-labs-projects`), all Sensitive:

| Variable | State |
|---|---|
| `VSM_ACCESS_KEY` | Set. HTTP Basic, any username. The value is in the macOS Keychain as "Vi Signal Mine access key" (`security find-generic-password -s "Vi Signal Mine access key" -w`) |
| `BRIGHTDATA_API_KEY` | Set. Bright Data account `hl_62bb110b`, the Attending Health account |
| `BRIGHTDATA_SERP_ZONE` / `BRIGHTDATA_UNLOCKER_ZONE` | `serp_api1` / `web_unlocker1`, the zones that account actually has |
| `VSM_MINER` / `VSM_DRAFTER` | `auto` |
| `VSM_OFFLINE` | `0` |
| `ANTHROPIC_API_KEY` | **Still blank.** Without it MINE uses one deterministic cluster, INSIGHT gives one theme per row and reads no tone, and REPORT has nothing to state at 2+ sources |

`bash scripts/setup-live.sh` sets the same variables interactively.

**A1. Zones.** The code defaults `dataweb_serp_api1` / `dataweb` do not exist on
account `hl_62bb110b` (live answer: `400 zone "dataweb_serp_api1" not found`).
They may belong to a different Vi Bright Data account; switching accounts means a
new key plus both zone variables.

**A2. Model id.** `claude-opus-5` is a current model and accepts the forced
`tool_choice` the client sends. Opus 5.5 and Fable 5.1 reject forced tool use,
so moving `VSM_LLM_MODEL` to either needs a client change.

---

## B. The live surface

**B1. Done** — and this entry was stale from the day it was written: the
pre-flight landed in the very next commit. `/healthz/brightdata`
(the route in `vsm/ui/app.py`, the probes in `vsm/mining/healthcheck.py`) makes one un-retried real call
each to SERP and Web Unlocker and reports pass/fail per product with the zone, the
latency and Bright Data's verbatim error. Discover is **not** probed — its API is
trigger-then-poll, so the cheapest honest probe costs a job plus a poll; a green
page does not vouch for a sweep's Discover leg. Still unrun against a live key,
which is B2's problem, not this one's.

**B2. Response shapes - verified live on 27 September 2026.** SERP (`brd_json=1`)
parses; the payload now also carries `ai_overview` and `images`, which the parser
ignores. Web Unlocker answers. **Discover returns `410 {"error":"Discover API is
no longer available"}`** on this account, although Bright Data's docs and its CLI
0.3.7 still call the same endpoint. The miner records the failure in
`coverage.json` notes and continues on SERP, so a sweep completes; the Discover
leg adds nothing until Bright Data restores it or the leg is removed.

**B3. Cost reconciliation — internal half done, invoice half still open.**

**Done, 2026-09-06.** The two modules that priced a run disagreed. `guards/cost.py`
carried its own `UNLOCKER_USD = 0.03` and `DISCOVER_USD = 0.0015` against
`mining/budget.py`'s $0.003 for both — so the estimate quoted in the pre-spend
interstitial ran 10x high on Unlocker and half on Discover, against a $5.00
`VSM_RUN_COST_CAP_USD`. `mining/budget.py` now owns every Bright Data price and
`guards/cost.py` reads them; `tests/test_cost.py` fails if the PRD figures drift or
the estimator re-declares one. The $0.03 was never a typo — it was an owner quote of
$30/1,000, recorded as disputed in `mining/miner.py`. PRD §13.1's verified $3/1,000
governs until an invoice says otherwise. Corrected ratio: **2x, not 20x**, which
also means page fetches are not the widest mining line — Discover results are, at
the same $0.003 each.

**Still open.** After the first live run, reconcile the estimate against the real
Bright Data invoice. Two things specifically: whether Unlocker bills at $3/1,000
(settling the owner's $30/1,000 quote), and whether Discover bills per returned
result at all — its $0.003 is derived from the PRD's "~600 page parses → ~$1.80"
line, not from a published unit price, which is why every Discover call record
carries `estimated=True`. The parent engine's recorded $0.0315 sweep is exactly one
Unlocker fetch plus one SERP call *at the old wrong price*, so treat it as computed,
not invoiced.

---

## C. The serverless execution limit (architectural)

**C1. Function timeout → probe band only on Vercel.** The 60s cap came from the
Hobby account the project started on. VI Labs is on Pro with Fluid compute, where
the maximum is 800s, so `vercel.json` now sets 800. `assert_band_allowed` still
refuses `standard`/`deep` on Vercel. Probe (2 queries × 10 results, 5 discover, 0
page fetches per cluster) fits with a wide margin: the first live probe sweep on
the deployment took 8.1s, INSIGHT 0.9s and REPORT 0.8s, all without an Anthropic
key. Model calls will add to INSIGHT and REPORT once the key is set.

**C2. Standard/deep on the deployment.** With 800s available (1800s in Vercel's
extended-duration beta for Python 3.14), a `standard` sweep may fit on the request
path with no queue. Measure a live `standard` run locally first; if it finishes
well inside 800s, relaxing D14 is a one-line change. Otherwise it needs work off
the request path: a queue/worker or a separate long-running host.
Today the bigger bands are local-only (which is the documented, honest state, not
a bug). Decide whether hosted probe-only is acceptable for launch or whether
async is in scope.

---

## D. Launch-state decisions

**D1. Done, 28 September 2026.** The fabricated "Tirzepatide for obesity - worked
example" topic (4 runs, 21 artifacts, all flagged synthetic) was deleted from
production through the app's own delete action. A full row-level backup is in
`var/backups/demo-topic-top-eaa2b67b3b-2026-09-28.json` (local, gitignored). The
seeder is a no-op while a database is configured (`vsm/demo.py:165`), so nothing
recreates it on production; local runs without a database still seed it.

**D2. Spend cap.** `VSM_RUN_COST_CAP_USD` defaults to $5.00 per run. Confirm
that ceiling is right for a shared production account.

---

## E. Polish (not blocking a live test)

**E1.** The "Trend" deliverable downloads as `momentum.json` (the artifact's real
name). Display name and filename differ — cosmetic. Renaming the artifact across
the pipeline is a larger, riskier change; deferred deliberately.

**E2.** The NPI author-resolver is a deliberate stub: `author_type` comes from
the venue's kind, not a resolved identity. This is the highest-value *future*
feature (the social-handle → NPI join), not a launch blocker.

---

## What is already done and verified

- FE: all routes render; encodings, layered depth, plain vocabulary shipped.
- BE: mutations work end to end.
- DB: **Postgres is live and durable** — verified by a write→read-in-a-separate-
  request→delete cycle on production.
- Deploy: Vercel's Git integration builds **production from every push to
  `build/vi-signal-mine-v1`** and a preview from every other branch, including
  `deploy`. `vercel --prod` and `setup-live.sh` upload the working tree instead.
  Previews share the production database and carry the same `VSM_ACCESS_KEY` as
  production since 28 September 2026; builds made before that serve without a
  password.
- "New report" is always available (header action + `/reports/new` hub).
- 730 tests pass, 5 skipped. The live path is exercised against a mocked
  transport in the suite and was run against the real Bright Data API on
  27 September 2026, locally and on production.
