# Handoff — 2026-08-27

Stopped cleanly here. Everything is committed, pushed and deployed. This file is
what a person (or an agent) needs to pick it up cold.

## Where it is

| | |
|---|---|
| Repo | `daniellazar-cpu/vi-signal-mine`, private. Branches `build/vi-signal-mine-v1` (work) and `deploy` |
| Live | https://vi-signal-mine-pink.vercel.app — production, serving, **read-write** |
| Tests | **527 passed, 1 skipped.** The skip is the Blob storage-contract suite, which needs a live Blob token |
| Working tree | clean at `cabc24c` |

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

## Storage: solved

There is a dedicated Vercel Blob store (`vsm-store`) connected to the project on
the `vi-labs-projects` team. The deployment is **read-write**: topics, runs and
artifacts survive across invocations, verified by creating a topic and reading it
back on three later requests, then running a full mine → insight → report chain
through the real forms.

`open_stores` prefers Postgres, then Blob, then SQLite, and logs its choice at
INFO. The team's existing Neon Postgres is deliberately untouched — it belongs to
a different project.

### The bug that made it look broken, and it was not the UI

Two defects, both found by adversarial verification rather than by use, and both
now fixed with tests that fail without the fix:

1. **Every write-path route 500ed.** `BlobRunStore.artifacts_dir` returns a
   `PurePosixPath` subclass standing in for a blob key. The UI treated it as a
   real path — `.stat().st_size` inside an `except OSError` raised
   `AttributeError` instead, killing every route that renders a deliverable card
   (run, snapshot, insight, report, topic detail), and `FileResponse` broke all
   ten downloads. Reads of pre-seeded data worked, so it surfaced only once a run
   was created on the deployment. The whole suite was green because every UI test
   used the one backend with real paths; `tests/test_ui_keyed_backend.py` now runs
   the UI against the keyed contract.

2. **Run creation was a coin flip.** `_next_seq` failed with "too much concurrent
   contention after 40 attempts" with one caller. The blob content host serves a
   stale body *and a stale ETag* — it ignores its own `s-maxage=0` and a
   cache-busting query string does not defeat it, only a request-side no-cache
   does. A compare-and-swap loop cannot survive a stale ETag: it PUT against a
   precondition that could no longer hold, took a real 412, re-read the same
   cached copy, and burned the retry budget. `get_content` now reads uncached,
   which is a correctness fix for run records too, not just the counter.

This pair is the "sometimes it does work" the tool was reported with.

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
