# Deployment — Vi Signal Mine

**Deployed 2026-08-25.** Vercel project `vi-signal-mine` under `daniellazar-1939`.

| | |
|---|---|
| Repository | https://github.com/daniellazar-cpu/vi-signal-mine (private) |
| Ship branch | `deploy` |
| Latest preview | https://vi-signal-mine-dghrgg083-daniellazar-1939s-projects.vercel.app |
| Production alias | https://vi-signal-mine.vercel.app — **inert by design**, see below |

## What is live, and what is not

The app is deployed and serving on a **preview** deployment, gated by Vercel
Deployment Protection. It runs, renders every screen, and reads and writes.

It is **not yet wired to spend money or to persist across invocations.** Two
things are outstanding, and both are yours to do because both involve secrets
or provisioning on your account.

## 1. The production alias refuses to serve, on purpose

`https://vi-signal-mine.vercel.app` answers **503 on every route**:

> D15: this is a production Vercel deployment, and the app refuses to serve any
> route here.

Vercel assigns a project's *first* deployment to production automatically, which
is how this got tested for real on day one. Protection here is Vercel preview
gating, and that covers previews only — so the guard is what keeps a deployment
that reaches a production domain inert rather than open with live API keys behind
it. Preview-only is a property of the code, not of a dashboard setting.

To deploy: `vercel` from the repo root. **Never `vercel --prod`.**

## 2. Add the secrets (yours to run — I do not handle your keys)

```bash
vercel env add ANTHROPIC_API_KEY preview
vercel env add BRIGHTDATA_API_KEY preview
vercel env add BRIGHTDATA_SERP_ZONE preview       # dataweb_serp_api1
vercel env add BRIGHTDATA_UNLOCKER_ZONE preview   # dataweb
vercel env add VSM_OFFLINE preview                # 0
vercel env add VSM_RUN_COST_CAP_USD preview       # 5.0
```

Until `VSM_OFFLINE=0` is set the deployment is hermetic: every screen works,
no outbound call is possible, nothing can be spent. That is a safe resting state,
not a broken one.

## 3. Provision Postgres (yours to click)

Vercel dashboard → Storage → Create Database → Postgres, attached to this project.
Then redeploy. Nothing else is needed: `resolve_db_url` reads
`POSTGRES_URL_NON_POOLING`, then `POSTGRES_URL`, then `DATABASE_URL`, and
`open_stores` logs at INFO which backend it chose.

**Why this is not optional.** `/tmp` on a serverless host belongs to one
invocation. The parent engine lost a real visitor's consent record exactly this
way — the write returned success and the container holding it was destroyed.
Without a provisioned database, topics and runs created on the deployment
disappear between requests, silently.

## 4. What the deployment will and will not run

- **`probe` band only.** `standard` and `deep` refuse with a message naming
  local execution. A sweep that dies at the function timeout leaves a half-written
  snapshot that the next momentum run treats as a real baseline — worse than a
  refusal.
- **INSIGHT is resumable.** It is the mode most likely to hit the 60-second
  ceiling on a large snapshot; each pass writes its artifact as it finishes and a
  re-request skips what is already done.
- Full-fidelity `standard` and `deep` runs stay local: `make run`.

## Verified on this deployment

- Production alias returns the D15 refusal on `/` ✓
- Preview deployment renders the topics screen and its empty state ✓
- Deployment Protection is active — reaching either required a bypass token ✓

## Not yet verified on the deployment

A live `probe` run end to end, and persistence across container turnover. Both
need step 2 and step 3 first. When you run them, record the wall-clock and the
real cost here — if INSIGHT cannot finish even with resume, note the snapshot
size at which it stopped being viable, because that number is the honest limit
of the probe-band decision.
