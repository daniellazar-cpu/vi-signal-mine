# Pending — to productionize Bright Data and make the site fully functional

Status as of `61042bc`. The engine is complete and
production-grade; the gap is that **the live Bright Data path has never run
against the real API** — every test to date uses a mocked transport. Everything
below is ordered by what blocks a first live run.

---

## A. Yours — keys and environment (nothing ships until these are set)

The one-command path is `bash scripts/setup-live.sh`, which does all of this in
the right order. By hand, every command needs `--scope vi-labs-projects` or the CLI
resolves to your personal account and reports "Deployment not found". In this order,
because the order matters:

1. `VSM_ACCESS_KEY` — **first.** With live keys behind no gate, the production
   guard deliberately refuses to serve.
2. `ANTHROPIC_API_KEY` — needed by INSIGHT (stance, clusters) and REPORT
   (drafting), and it improves MINE (query expansion; without it MINE falls back
   to a single deterministic cluster).
3. `BRIGHTDATA_API_KEY`.
4. `BRIGHTDATA_SERP_ZONE` (default `dataweb_serp_api1`) and
   `BRIGHTDATA_UNLOCKER_ZONE` (default `dataweb`) — **confirm these are the real
   Vi zones your key can reach** (A1 below).
5. `VSM_OFFLINE=0` — the master switch; until then the app is inert and cannot
   spend.
6. Redeploy.

I will not handle the secret values. I can stage the exact `vercel env` commands
for you to run.

**A1. Confirm zone access.** The defaults are `dataweb_serp_api1` / `dataweb`.
The first live call fails cleanly if the key cannot reach them. Worth confirming
against the Bright Data dashboard before the test.

**A2. Confirm the model id.** Default is `claude-opus-5` (`VSM_LLM_MODEL`).
Confirm the account has access, or set it to one it does.

---

## B. The unproven surface — the first live run is the real test

The request/response parsers for SERP, Discover and Web Unlocker are tested only
against `httpx.MockTransport` with **assumed** Bright Data response shapes. The
first live run is where those shapes get verified.

**B1. Done** — and this entry was stale from the day it was written: the
pre-flight landed in the very next commit. `/healthz/brightdata`
(the route in `vsm/ui/app.py`, the probes in `vsm/mining/healthcheck.py`) makes one un-retried real call
each to SERP and Web Unlocker and reports pass/fail per product with the zone, the
latency and Bright Data's verbatim error. Discover is **not** probed — its API is
trigger-then-poll, so the cheapest honest probe costs a job plus a poll; a green
page does not vouch for a sweep's Discover leg. Still unrun against a live key,
which is B2's problem, not this one's.

**B2. Response-shape validation.** If Bright Data's live JSON differs from the
mocked fixtures (field names, nesting, empty-result encoding), the parsers in
`vsm/mining/{serp,discover,unlocker}.py` need adjusting. Cannot be known until a
real call is made.

**B3. Cost reconciliation.** `budget.py` prices SERP at $0.0015, Unlocker/Discover
at $0.003. After the first run, reconcile the estimate against the real Bright
Data invoice and adjust if the published prices have moved.

---

## C. The serverless execution limit (architectural)

**C1. 60-second timeout → probe band only on Vercel.** `assert_band_allowed`
refuses `standard`/`deep` on Vercel because they add page fetches and a wider
sweep that will not finish in 60s. Probe (2 queries × 10 results, 5 discover, 0
page fetches per cluster) is designed to fit — **validate that a real probe
sweep actually completes under 60s** on the first run; live calls are slower than
mocks.

**C2. Standard/deep need async execution to be hosted.** A fully functional
hosted tool that runs the bigger bands needs work off the request path — a
queue/worker, Vercel background functions, or a separate long-running host.
Today the bigger bands are local-only (which is the documented, honest state, not
a bug). Decide whether hosted probe-only is acceptable for launch or whether
async is in scope.

---

## D. Launch-state decisions

**D1. The synthetic demo topic on production.** A fabricated "Tirzepatide"
example is sitting there. It is **leftover data, not an ongoing seed** — the
seeder is a no-op now that a database is configured (`vsm/demo.py:165`), so
deleting it is permanent and nothing recreates it. Decide: keep it as an
onboarding example, or clear it before the first real client-facing run. Real runs
are non-synthetic and the demo banner correctly disappears for them.

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
- Deploy: `origin/deploy` and `origin/build/vi-signal-mine-v1` are both at
  `61042bc`. (The *local* `deploy` checkout can lag — `git fetch && git branch -f
  deploy origin/deploy`. Nothing builds from it: `setup-live.sh` uploads the working
  tree.)
- "New report" is always available (header action + `/reports/new` hub).
- 722 tests pass, 5 skipped; the whole live path is exercised against a mocked
  transport.
