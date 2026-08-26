# Handoff — 2026-08-26

Stopped cleanly here. Everything is committed, pushed and deployed. This file is
what a person (or an agent) needs to pick it up cold.

## Where it is

| | |
|---|---|
| Repo | `daniellazar-cpu/vi-signal-mine`, private. Branches `build/vi-signal-mine-v1` (work) and `deploy` |
| Live | https://vi-signal-mine.vercel.app — production, serving, **read-only** |
| Tests | **489 passed, 1 skipped.** The skip is the Blob storage-contract suite, which needs a live Blob token |
| Working tree | clean at `6b228a3` |

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

## The one thing blocking full function

**There is no durable storage, so the deployment is read-only.** Every mutating
route returns 409 and the controls that cannot work are not rendered. The seeded
example is fully explorable; you just cannot create your own topic on the
deployment.

This is not a bug — it is the honest response to storage that cannot hold a
write. `/tmp` on a serverless host belongs to one invocation, so a write returns
success and vanishes when the container recycles. The app now refuses rather
than losing your work silently.

### Why there is no store, and it was my doing

I provisioned a Vercel Blob store via the API and connected it. The agent
building against it ran an 8-thread concurrency test to prove the `seq` ordering
held under contention — the right test, and it found two real bugs — but it blew
through the Hobby operations quota. The store went to
`limits-exceeded-suspended`, I deleted it, and Vercel now refuses to create
another: `usage_threshold_limits_reached`, account level.

I also removed the dead `BLOB_READ_WRITE_TOKEN` from the project env. Left in
place it would have been **worse than no store**: `storage_is_durable()` reads
that token, so the app would have dropped out of read-only mode, accepted
writes, and failed every one against a store that no longer existed — silent
loss instead of an honest refusal.

### Making it read-write — one step, and the code needs no change

`open_stores` prefers **Postgres**, then **Blob**, then SQLite. Any one of these
flips the deployment to full read-write:

1. **Raise the Blob limit** (dashboard → Storage → billing), create a store,
   connect it to the project. The token injects itself.
2. **Or connect any Postgres** — Neon, Supabase, anything. Set
   `POSTGRES_URL_NON_POOLING` (preferred; the pooled URL is PgBouncer in
   transaction mode and breaks prepared statements). This takes precedence over
   Blob.

Then redeploy. `open_stores` logs which backend it chose at INFO.

## Also outstanding, and genuinely yours

**API keys.** I will not handle your secrets.

```bash
vercel env add ANTHROPIC_API_KEY production
vercel env add BRIGHTDATA_API_KEY production
vercel env add BRIGHTDATA_SERP_ZONE production      # dataweb_serp_api1
vercel env add BRIGHTDATA_UNLOCKER_ZONE production  # dataweb
vercel env rm VSM_OFFLINE production
```

Until `VSM_OFFLINE=0`, the deployment is hermetic: every screen works, no
outbound call is possible, nothing can be spent. That is a safe resting state,
not a broken one.

**Set `VSM_ACCESS_KEY` before adding live keys.** With keys present and no gate,
the production guard refuses to serve — deliberately. On this plan Vercel gates
preview deployments only, so a production URL is reachable by anyone holding it,
and live keys behind an open URL can spend real money. Gate first, then add keys.

**Two consequences of running offline**, both honest rather than defects: the
clinician–patient gap reads `NE` on most themes because no stance classifier
runs without an Anthropic key; and every seeded row is flagged `synthetic` with a
fabrication notice carried into the artifacts, so a downloaded report cannot be
mistaken for real collection.

## Where the redesign got to

The owner's verdict on the deliverables page was that it looked like 1990s
markdown. The plan is at
`docs/superpowers/plans/2026-08-26-report-presentation.md` — it opens with a
table of all sixteen asks from the whole build and where each stands.

An eleven-agent workflow was auditing, rebuilding and adversarially verifying
it. **The build phase landed** (`dbf8746`, "Typeset the report as a client
document and tier the deliverables") and is deployed. The four adversarial
verification lenses — regression, a design director judging the rendered
screens, an independent crawler checking that every citation anchor resolves to
an id that exists, and an accessibility pass — **did not run.** Stopped before
them.

**So the redesign is shipped but unverified.** What I did confirm by hand before
deploying: every route 200, and no raw markdown on any page. What nobody has
checked: whether it is actually good, whether any citation anchor points at a
missing id, and whether the accessibility work survived.

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
- Run the adversarial verification the workflow did not reach.
