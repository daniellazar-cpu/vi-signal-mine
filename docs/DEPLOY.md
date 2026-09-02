# Deployment — Vi Signal Mine

**Rewritten 2026-09-02.** The previous version described the 25 August state and had
gone wrong on nine separate facts — the account, the ship rule, whether production
serves, which environment the env vars target, and whether Postgres still needed
provisioning. It drifted because it duplicated the commands that live in
`scripts/setup-live.sh`, so this version deliberately does not: the script is the
executable truth, and this page says only what the script cannot.

| | |
|---|---|
| Repository | https://github.com/daniellazar-cpu/vi-signal-mine (private) |
| Vercel project | `vi-signal-mine`, on the **`vi-labs-projects`** team |
| Live | https://vi-signal-mine-pink.vercel.app — **production, serving, read-write** |
| Ship | `bash scripts/setup-live.sh`, or `vercel --prod --scope vi-labs-projects` |
| Storage | Neon Postgres `neon-rose-compass`, attached. **Already provisioned** |

**`--scope vi-labs-projects` is not optional.** Without it the CLI resolves to your
personal account and reports "Deployment not found", which reads as a broken
deployment and is not one.

## Production serves. It refuses exactly one combination

The old rule here was "never `vercel --prod`", written when the guard refused *all*
production traffic. It does not: `assert_serveable` in `vsm/platform.py` refuses
only **live keys behind no gate** — because on this plan Vercel gates previews only,
so a production URL is reachable by anyone holding it and live keys behind an open
URL can spend real money.

Two ways to be safe, and the app checks for both:

- **`VSM_ACCESS_KEY` set** → the app gates itself. `RequireAccessKey` in
  `vsm/platform.py` is HTTP Basic at the ASGI layer on both entrypoints: any
  username, the key as the password.
- **`VSM_OFFLINE=1`** (the default) → inert. Every screen renders, no outbound call
  is possible, nothing can be spent. A safe resting state, not a broken one.

So the order matters, and `scripts/setup-live.sh` enforces it: **gate first, then
keys.** Set the keys with no gate and production correctly refuses to serve.

## Going live

```bash
bash scripts/setup-live.sh
```

It generates or takes the access key, prompts for the Anthropic key (optional — skip
it for collection-only) and the Bright Data key, flips `VSM_OFFLINE` to 0, and
redeploys. Keys are read with `read -s`: never echoed, never written to a file,
never in your shell history. Then open
[`/healthz/brightdata`](https://vi-signal-mine-pink.vercel.app/healthz/brightdata)
and press **Run connection test** — one real call each to SERP and Web Unlocker, so
a wrong key or zone costs a few cents instead of surfacing mid-sweep.

**Do not put `VSM_OFFLINE` in `vercel.json`.** It was pinned there once, and
`vercel.json`'s `env` overrides the dashboard variable — so a live launch would have
reported success and silently done nothing. `tests/test_deployment_scaffolding.py`
now fails if it comes back.

## Storage

Neon Postgres, attached through the Vercel marketplace. `resolve_db_url` in
`vsm/backends/dburl.py` reads `POSTGRES_URL_NON_POOLING`, then `POSTGRES_URL`, then
`DATABASE_URL`; `open_stores` logs at INFO which backend it chose.

Use the **non-pooling** URL for anything running migrations or the storage-contract
suite — the pooled one is PgBouncer in transaction mode and breaks prepared
statements.

**Why a real database is not optional.** `/tmp` on a serverless host belongs to one
invocation. The parent engine lost a real visitor's consent record exactly this way:
the write returned success and the container holding it was destroyed.

## What the deployment will and will not run

- **`probe` band only** — enforced by `assert_band_allowed` in `vsm/platform.py`.
  `standard` and `deep` refuse with a message naming local execution. A sweep that dies at the 60-second function
  timeout leaves a half-written snapshot that the next momentum run treats as a real
  baseline — worse than a refusal.
- **INSIGHT is resumable.** It is the mode most likely to hit the ceiling on a large
  snapshot; each pass writes its artifact as it finishes and a re-request skips what
  is already done.
- Full-fidelity `standard` and `deep` runs stay local: `make run`.

## Verified, and not

**Verified on production:** every route serves; Postgres durability by a
write → read-in-a-separate-request → delete cycle; the HTTP Basic gate; an
independent crawl found 0 broken links across 36–38 pages.

**Not verified:** a live `probe` run end to end, because no Bright Data or Anthropic
key has ever been set. When you run one, record the wall-clock and the real cost
here — and if INSIGHT cannot finish even with resume, note the snapshot size at
which it stopped being viable, because that number is the honest limit of the
probe-band decision.

See `docs/PENDING.md` for everything still outstanding, and `docs/HANDOFF.md` for
how to pick the project up cold.

---

*Line numbers are deliberately absent from the references above. An earlier version
of this page carried them and three of five were already wrong — one broken by the
very commit that wrote it. A file and a symbol name survive an edit; a line number
does not.*
