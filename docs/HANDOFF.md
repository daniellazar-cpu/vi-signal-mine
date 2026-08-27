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

## Storage — and the honest recommendation

There is a dedicated Vercel Blob store (`vsm-store`) connected to the project on
the **`vi-labs-projects`** team. Topics, runs and artifacts survive across
invocations. The full chain — topic, mine, insight, report — ran **8/8 green** on the
deployment after the last of these fixes, having been 2/10 before them.

### Use Postgres instead. This is the main recommendation of the day.

`open_stores` already prefers Postgres over Blob, and the Postgres backend is
built and tested. Switching is one environment variable and a redeploy:

```bash
vercel env add POSTGRES_URL_NON_POOLING production --scope vi-labs-projects
```

Use the **non-pooling** URL: the pooled one is PgBouncer in transaction mode and
breaks prepared statements. Any Postgres works — Neon, Supabase. The team has a
Neon on a *different* project; the backend takes a `schema=`, so it can be
shared without collision.

**Why it matters.** Vercel Blob is an object store being used as a database, and
five separate defects fixed today were all consequences of that one choice:

| What broke | Because |
|---|---|
| Run creation was a coin flip | A compare-and-swap counter cannot be atomic on a store with no atomic primitive. Every `GET` returned 200, the following conditional `PUT` returned 412, forty times |
| Records read back stale | The content host serves a stale body *and* ETag, ignores its own `s-maxage=0`, and a cache-busting query string does not defeat it |
| A cold container reported existing blobs as missing | No secondary index, so discovery went through the list API, which is eventually consistent |
| The home page 504ed | No secondary index, so "this topic's runs" means reading *every* run blob's content. 13,144 GETs for one render |
| The report step failed intermittently | A blob is not readable from every edge the instant its write returns. Caught in the act: on a failing run, every artifact the function could not read returned 200 to an external check moments later — from a different region |

Each has a fix and a test that fails without it. But they are five workarounds
for a substrate mismatch, and a relational database with a primary key, an
index, a real sequence and read-your-writes deletes all five problems rather
than mitigating them. **Recommend doing this before the tool goes in front of
anyone.**

### What the Blob path cost, recorded so it is not re-learned

- `seq` is a nanosecond hybrid clock with an in-process monotonic clamp, not a
  counter. Safe only because `seq` is a pure sort key — both blob stores
  `data.pop("seq")` before building the model. See `_next_ordinal`.
- Content reads send request-side `no-cache`, and there is a **request-scoped**
  identity map in front of them. It is not a TTL cache and must not become one:
  it is correct only within one request, and serverless containers are reused.
  Cleared by middleware in `vsm/ui/app.py`.
- The content host is derived from the token
  (`vercel_blob_rw_<storeId>_<secret>` -> `<storeid>.public.blob.…`) so no read
  path consults the list API.
- `vsm/storage.py:read_required` retries a read the caller knows must succeed,
  opt-in per backend via `reads_may_lag`. Two traps, both hit:
  it must **clear the identity map between attempts**, or it retries against the
  memoised miss and does nothing (that is how its first version shipped, and
  production stayed at 2/10); and the waiting budget must belong to the
  *operation*, not the read — `run_report` needs seven artifacts, so a per-read
  budget multiplied the wait by seven and pushed a genuine absence past the
  60-second ceiling, while shrinking the per-read budget simply brought the
  original failure back. `ReadDeadline` is shared across all seven.
- Reads whose absence is a legitimate answer must stay plain: `_existing_artifact`
  (resume), the momentum loop, and the deliverable cards' ten-name probe. A test
  asserts the first two do not retry.

### The bug that made it look broken, and it was not the UI

`BlobRunStore.artifacts_dir` returns a `PurePosixPath` standing in for a key.
The UI treated it as a real path — `.stat().st_size` inside an `except OSError`
raised `AttributeError` instead, killing every route that renders a deliverable
card, and `FileResponse` broke all ten downloads. Reads of pre-seeded data
worked, so it surfaced only once a run was created on the deployment. The whole
suite was green because every UI test used the one backend with real paths;
`tests/test_ui_keyed_backend.py` now runs the UI against the keyed contract.

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

Every page was slow, and none of it was compute.

| Page | Before | After |
|---|---|---|
| Topics index | 11.6s | 0.72s |
| `/deliverables` | 10.3s | 0.69s |
| A topic page | 4.7s | 0.79s |
| Report | — | 0.81s |

Two separate contributions, worth keeping apart because only one of them
survives the store growing again:

**The fixes, ~4x at any size** (measured at 61 topics: index 11.6s → 3.0s). A
flat key-value store with no secondary index answers "which runs belong to this
topic?" by reading every run record. That much is inherent. Doing it one request
at a time, and re-doing it per topic, was not:

- prefix listings memoised per request — the index called `for_topic` once per
  topic and every call listed the *same* prefix, 61 identical round trips
- `get_many`, a small thread pool for content reads, which are independent GETs
  against a CDN with nothing to serialise them for
- `prefetch_artifacts`, so the index's per-snapshot `signals.json` reads and a
  run page's ten card probes each go out in one batch
- `/deliverables` stops at the first topic with a report; it used to scan every
  topic and keep the last, on a page that shows no run data at all
- search is applied *before* any run lookup, so a narrow query turns the most
  expensive page into one of the cheapest

**The rest is a smaller store.** 61 verification topics of mine are deleted, and
that alone took the index from 3.0s to 0.58s. If the store grows to hundreds of
topics the index will get slow again — the reads scale with the number of runs
and only the constant factor was fixed. **That is the strongest practical
argument for the Postgres switch above**, where "this topic's runs" is an index
lookup rather than a scan.

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
