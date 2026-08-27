# Handoff — 2026-08-27

Stopped cleanly here. Everything is committed, pushed and deployed. This file is
what a person (or an agent) needs to pick it up cold.

## Where it is

| | |
|---|---|
| Repo | `daniellazar-cpu/vi-signal-mine`, private. Branches `build/vi-signal-mine-v1` (work) and `deploy` |
| Live | https://vi-signal-mine-pink.vercel.app — production, serving, **read-write** |
| Tests | **591 passed, 1 skipped.** The skip is the Blob storage-contract suite, which needs a live Blob token |
| Working tree | clean at `e00a913` |

## What works right now

The engine is complete and the whole pipeline runs: a topic becomes a dated
snapshot, seven analysis passes turn that into findings, and a report comes out
the other end with citations that resolve back to the rows behind them.

The deployment serves a **deterministic worked example** — "Tirzepatide for
obesity" with two snapshots, so momentum and anomalies have a real baseline
rather than saying "no prior snapshot". Every screen is reachable, all ten
artifacts download, and an independent crawl of production found **0 broken
links across 36–38 pages**.

Verified at the moment of stopping: every route 200, and no raw markdown reaches
any page.

## Storage: Postgres

The deployment runs on a **Neon Postgres** (`neon-rose-compass`), provisioned
through the Vercel marketplace and connected to the project on the
**`vi-labs-projects`** team. `open_stores` already preferred Postgres, so the
switch was configuration plus two fixes below. The Blob store is still attached
and is now the fallback; the data in it is orphaned and can be deleted.

This was the main recommendation of the previous pass, and it was the right one:
five defects fixed earlier that day were all consequences of using an object
store as a database, and Postgres removes the conditions rather than mitigating
them.

### The near-miss, recorded because it is not obvious

Setting a database URL was, on its own, enough to take the deployment down
completely. Vercel installs **only** the core dependency list from
`pyproject.toml` — optional extras are never resolved there — and `psycopg` was
deliberately an extra. `open_stores` would have found a URL, imported the
Postgres backend, and raised `ModuleNotFoundError` on every request. Caught
before deploying only because env changes do not take effect until the next
build.

- `psycopg[binary]` is a core dependency now. The original reasoning (a local
  install and the hermetic suite must work without a driver) still holds — having
  the driver installed connects to nothing.
- `open_stores` falls back to the next backend with an error log naming the
  missing module, rather than propagating the import failure. A configured
  database with no driver is a deployment mistake; serving nothing is not the
  right answer to it.

### The Postgres backend had never run against a real database

It had only ever been exercised against SQLite and fakes. The storage contract
suite now passes against Neon, and the first run found a bug no fake could have:
`for_topics` shipped with `SELECT *` where the table carries a `seq` column its
row-mapper does not take — ten values unpacked into nine.

To run it yourself:

```bash
VSM_TEST_DATABASE_URL="$(grep -m1 '^POSTGRES_URL_NON_POOLING=' .env.local | cut -d= -f2-)" .venv/bin/python -m pytest -q tests/test_storage_contract.py
```

`.env.local` is written by `vercel env pull` and is gitignored. Use the
**non-pooling** URL — the pooled one is PgBouncer in transaction mode and breaks
prepared statements.

## Also outstanding, and genuinely yours

**API keys.** I will not handle your secrets.

The `--scope` is not optional. The project lives on the **`vi-labs-projects`**
team, and without it the CLI resolves to your personal account and reports
"Deployment not found" — which looks like a broken deployment and is not one.

```bash
vercel env add VSM_ACCESS_KEY production --scope vi-labs-projects
vercel env add ANTHROPIC_API_KEY production --scope vi-labs-projects
vercel env add BRIGHTDATA_API_KEY production --scope vi-labs-projects
vercel env add BRIGHTDATA_SERP_ZONE production --scope vi-labs-projects      # dataweb_serp_api1
vercel env add BRIGHTDATA_UNLOCKER_ZONE production --scope vi-labs-projects  # dataweb
vercel env rm VSM_OFFLINE production --scope vi-labs-projects
```

`VSM_ACCESS_KEY` is listed first deliberately — see below.

Both key variables currently exist as **blank placeholders**. Blank is read as
absent throughout (`vsm/config.py`'s `_raw`), so they are harmless as they
stand; setting them is what arms live collection.

Until `VSM_OFFLINE=0`, the deployment is hermetic: every screen works, no
outbound call is possible, nothing can be spent. That is a safe resting state,
not a broken one.

**One other thing that still needs you.** `BLOB_READ_WRITE_TOKEN` sits in the
project as **Non-sensitive** (Vercel's default for an integration-injected
variable), so its value is partly readable in `vercel env ls`. Not exposed
publicly, but it is a write credential and would be better re-added as sensitive.

**Set `VSM_ACCESS_KEY` before adding live keys.** With keys present and no gate,
the production guard refuses to serve — deliberately. On this plan Vercel gates
preview deployments only, so a production URL is reachable by anyone holding it,
and live keys behind an open URL can spend real money. Gate first, then add keys.

**Only the `probe` band runs on the deployment** (D14). A `standard` or `deep`
sweep does not fit inside a Vercel function's timeout, and the app says so on a
clear error page rather than timing out halfway. Run those locally, where there
is no timeout to race. This is by design, not a limitation to fix.

**Two consequences of running offline**, both honest rather than defects: the
clinician–patient gap reads `NE` on most themes because no stance classifier
runs without an Anthropic key; and every seeded row is flagged `synthetic` with a
fabrication notice carried into the artifacts, so a downloaded report cannot be
mistaken for real collection.

## Speed

Every page was slow, and none of it was compute — it was storage round trips.

| Page | Before | After |
|---|---|---|
| Topics index (1 topic) | 11.6s* | 0.68s |
| Topics index (101 topics) | — | 0.73s |
| `/deliverables` | 10.3s | 0.63s |
| Topic page | 4.7s | 0.72s |
| Snapshot / insight / report | — | 0.85 – 1.12s |

\* measured at 61 topics on the Blob backend.

Four rounds, and the order matters because each exposed the next:

1. **Stop re-reading.** Prefix listings and content reads memoised per request.
   The index called `for_topic` once per topic and every call listed the *same*
   prefix — 61 identical round trips for one render. `/deliverables` scanned
   every topic and kept the last match, on a page that shows no run data at all.
2. **Stop serialising.** `get_many` puts independent CDN reads on a small pool;
   `prefetch_artifacts` batches the index's per-snapshot `signals.json` and each
   run page's ten card probes. Blob index: 11.6s → 3.0s at 61 topics.
3. **Stop scaling with the list.** Postgres alone was faster but still linear —
   0.96s at 10 topics, 1.84s at 40, about 30ms each, because the page still
   asked per topic. `for_topics` answers the whole index in one query. Measured
   flat afterwards: **0.73s at 101 topics**, no upward trend.
4. **Batch artifacts on Postgres too.** `prefetch_artifacts` existed only on the
   blob backend, so after the migration the card-rendering pages were back to a
   query per artifact. One `UNNEST` statement instead; ~25% off those pages.

Search is also the cheapest speedup available and worth knowing about: it is
applied *before* any run lookup, so a narrow query skips the work entirely.

**What is still linear:** nothing on the index. The artifact-heavy pages
(snapshot, insight, report) read a fixed number of artifacts per run, so they do
not grow with the store either. The report view's own content reads do not go
through `prefetch_artifacts` — that is the remaining ~0.3s on the slowest page,
and the obvious next thing if it ever matters.

## Managing the list

The list had grown to sixty topics with no way to tell the real ones apart.

- Search across name, brand, molecule, therapeutic area and competitors. All
  words must match — an any-word search over sixty rows is no narrower than no
  search.
- Six sorts, four filters. `Has a trend (2+)` is the analytically meaningful one:
  momentum and anomaly mean nothing on a single snapshot.
- All server-side and in the URL, so a view is shareable, bookmarkable and
  printable, and works with scripting off.
- **Delete**, new on the protocol and all four backends, removing the runs and
  their artifacts — the artifacts are the bulk of what a topic occupies.
  Confirm page rather than a dialog, tally first, POST-only for the destructive
  step, runs deleted before the topic so a half-failure stays retryable.

One worked example is left on the deployment — "Tirzepatide for obesity", two
snapshots so momentum and anomaly have a real baseline, with an insight and a
report. Delete it in one click if you would rather start empty; the demo seeder
will not recreate it, because it is a no-op whenever durable storage is
configured.

## Where the redesign got to

Shipped **and verified**. Four adversarial lenses ran against it — regression, a
design director on the rendered screens, an independent crawler, and an
accessibility pass. Every finding is fixed.

The design director's verdict on the report view: it is a document now, not a
page of data, and would go in front of a client. Confirmed by that pass: no raw
markdown anywhere, findings quotable with resolving citations, Figure 1 treated
as a real numbered figure with a table equivalent, Vi Violet reserved to the one
primary action and the data marks.

Fixed from the four lenses:

| Lens | Finding |
|---|---|
| Regression | Figure 1's net-stance cells printed a bare em dash where `pulse_report.md` states "not read — no patient-class signal in this theme", so the page was less honest than the document it previews. The test covering it asserted only that a dash appeared — it locked the defect in |
| Crawl | The two production outages above |
| A11y | Plot text at 4.03:1 (below AA) — and the design system's own token file already said that gray is for dividers and `--fg2` for text, so this broke a written rule and shipped in the client figure. Validation errors not associated with their fields. Collapsed `<details>` printing as an empty gap. The current snapshot marked by colour alone |
| Craft | The primary deliverables grid used `auto-fill`, so one macro rendered 2x2 on the report and 3-wide-with-an-orphan on the wider page. Wide tables scrolled but gave no hint they did |

Contrast is now a computed assertion rather than a grep. Writing that test
surfaced a smaller instance of the same class: a comment naming
`--vi-gray-500:` parsed as a declaration, and the reference assertion silently
*skipped* instead of measuring.

**A recurring pattern worth carrying forward.** Fifteen times in this build a
test asserted a property it never exercised. The two rules that caught most of
them: when two code paths are expected to agree on your fixture, the fixture
cannot prove which one ran; and a guard behind a stricter guard is never reached
by a fixture that trips the outer one. Every fix in this round was checked by
reverting the source and confirming the new test actually fails.

## If you pick this up

- `make install && make test` then `make run`. Local runs have full write
  capability — no database needed, because a local process reads and writes one
  directory.
- Read `docs/superpowers/specs/2026-08-25-vi-signal-mine-design.md` for the 18
  recorded decisions. Several close off options that look open.
- `docs/research/2026-08-25-social-intelligence-landscape.md` is why the
  `analysis/` package exists: collection is a commodity, the transformation
  ladder is the product.
- **The highest-value unbuilt thing** is the social-handle → NPI join. It is
  permitted (the licences allow it) and it is the moat: CREATION.co sells 3M+
  verified HCP profiles as its whole differentiator, and Vi has 7.24M HCPs in
  Provider360 plus an NPI↔HEM bridge. `vsm/analysis/authorclass.py` is the seam
  it drops into without touching stance or dual-lens. It deserves its own
  session and should not be smuggled into a UI project.
