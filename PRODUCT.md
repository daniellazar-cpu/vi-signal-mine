# Vi Signal Mine — product truth

*Sourced from `docs/superpowers/specs/2026-08-25-vi-signal-mine-design.md` (18 recorded
decisions) and `docs/research/2026-08-25-social-intelligence-landscape.md`, not inferred.
Anything genuinely assumed is marked **[assumed]**.*

## The mechanism, in one sentence

It watches what is being said about a healthcare brand or product online, and turns that
into intelligence — corroborated, split by who is speaking, and measured against the same
topic a week earlier.

## Who uses it, and the real scene

A Vi Labs analyst — a data person, not a marketer — at a desk, on a laptop, running it
locally against real API keys that cost real money. They are producing something they will
hand to a client in a meeting. **[assumed]** Daytime office light, single monitor,
possibly on a plane with no network.

The reader of the *output* is a commercial lead at a pharma client. They never touch this
tool; they receive its report.

## What this surface must prove

That the numbers can be trusted. The competitive research is unambiguous: nobody sells
collection, and the rung a vendor can credibly claim is their price. This tool's claim is
provenance — every figure traceable to a dated row with a URL. The interface has to make
that feel true, not merely stated.

## The task

1. Define a **topic** (brand, molecule, competitors, therapeutic area, spend band).
2. Confirm the spend, because it is real money on a shared account.
3. **MINE** a dated snapshot.
4. **INSIGHT** — seven passes over it: entities, corroboration, themes, stance by author
   class, the HCP-versus-patient gap, momentum against prior snapshots, anomalies.
5. **REPORT** — four artifacts, one of them client-deliverable.

Momentum needs a baseline, so a topic is watched repeatedly. The unit that carries history
outlives any single run.

## States that matter more than the happy path

- **No prior snapshot.** Momentum and anomaly say so in words. They never draw an empty
  chart, because an empty chart reads as "nothing is happening".
- **Nothing comparable.** A theme only one side discussed has no divergence and states why.
  Silence is not agreement.
- **Stopped on budget.** A distinct terminal state, not a failure. Partial rows kept.
- **A guard blocked the report.** An unciteable claim, a forecast, a banned term.
- **A venue answered with nothing.** Named, because a silent filter is indistinguishable
  from finding nothing.

## Hard constraints

FastAPI + Jinja2 with `StrictUndefined`. No CDN, no external font, no build step, works
with JavaScript disabled, renders with zero network. Local-first, no auth. Also deploys to
Vercel as a gated preview, where only the cheapest spend band may run.

## Brand commitments

None inherited. This is a standalone tool, not a Vi-branded property. **[assumed]** — the
spec names no visual authority and the parent engine's design is deliberately not carried
over.

## What would make a polished result feel wrong

Anything that makes an uncertain number look confident. The whole build has been a fight
against exactly that: thirteen tests found asserting properties they never exercised, four
artifacts caught stating something specific and false, a cost cap that spent 3.6× its
limit. A surface that renders `None` as `0`, or hides that a venue returned nothing, would
undo the engine's discipline in the last inch.
