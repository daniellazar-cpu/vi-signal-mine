# Report presentation — plan

**Date:** 2026-08-26 · **Status:** ready to build
**Trigger:** *"what the hell is this it looks like markdown from the 90s, I need nice UI with reports which I can eventually show the customers."*

---

## 1. What you have asked for, across the whole build

Consolidated so nothing gets dropped again. Every line is something you said, not
something I inferred.

| # | The ask | State |
|---|---|---|
| 1 | Fork the listening/mining mechanism out of Attending Health, standalone | Done |
| 2 | Same Bright Data and Anthropic keys | Done — `.env`, same zones |
| 3 | Choose a step: just mine, or insights, or content | Done — MINE · INSIGHT · REPORT, chainable |
| 4 | **Pulse and awareness**, not education — what is said about a customer's brand | Done — drove the rev-2 rewrite |
| 5 | Research Tastewise and peers: how they transform and package | Done — 11 companies, cited |
| 6 | Findings **with citations, links, traceback** | Done — provenance appendix |
| 7 | "Things worth considering" — suggestions, never decisions | Done — guarded |
| 8 | Repo per project, nothing left local | Done — private repo |
| 9 | Vercel, as its own app | Done — live |
| 10 | Only the topic required; guide me through the rest | Done — one required field |
| 11 | **The deliverables are the moat. High fidelity. Showable to customers.** | **This plan** |
| 12 | A screen showing what the deliverables will be, before running | Built, but looks like a file list — **this plan** |
| 13 | Match the Vi design system | Adopted; the report itself never got the treatment — **this plan** |
| 14 | High fidelity, clickable, real UI/UX craft | Partly — **this plan** |
| 15 | It must actually work, no dead ends | Done — 0 broken links, verified on production |
| 16 | Set up a database if I can | **Done** — Vercel Blob provisioned and connected by me |

## 2. Why the current output is wrong

The screenshot is a catalogue of files. Named precisely:

1. **The filename is the loudest element on every card.** `pulse_report.md` in mono
   competes with the title. The filesystem is the hero; the deliverable is not.
2. **Samples show raw markdown.** `**cost** is corroborated on 12 independent
   sources.` Unrendered syntax is the single strongest signal that something is
   unfinished — it is the whole "1990s" impression in one detail.
3. **Actions are bare text links.** `Download pulse_report.md ↓  What this is ↗`
   where there should be controls with states.
4. **Ten cards at one weight.** The client-ready report is presented as equal in
   importance to `coverage.json`. Nothing tells the eye what matters.
5. **The report view is a document dump.** It has the right sections and its
   citations resolve, but no title page, no styled findings, no confidence as a
   visual, no figure treatment. It reads as a README, not as something a pharma
   client accepts in a meeting.

The deeper error is mine and it is one level up: **I built a page that catalogues
artifacts when the job was to present reports.** That is the moat you have pointed
at four times.

## 3. The design intent

The Vi system is already committed: white canvas, black structure, Vi Violet as
the single signal, Neue Montreal, true hairlines. Nothing about the world changes.
What changes is what the world is applied *to*.

**Principle: a report is a document, not a page of data.** The reference is a
pharma commercial review deck or a medical journal article — something whose
authority comes from typography and restraint, where the reader believes it before
reading a word.

### 3.1 The report view becomes a client-facing document

- **A title block that reads as a cover**: topic, the dated window covered, the
  snapshot it rests on, and the confidence summary. Generous space. This is the
  first thing a client sees.
- **Findings as designed statements, not table rows.** Each corroborated finding
  gets its claim set large, its confidence as a **badge** rather than a word in a
  cell, its source count stated, and its citations as superscript references that
  resolve to the appendix. One finding should be quotable straight off the screen.
- **The forest plot becomes a figure** — numbered, captioned, with its legend, the
  way a journal figure is. It is the centrepiece, not an inset.
- **Tables typeset properly**: tabular numerals, hairline rules, no zebra
  striping, aligned decimals, a real caption above each.
- **The appendix reads as an appendix** — smaller type, a reference number per
  row, and the reciprocal link back to the claim that cited it.
- **`None` still renders as its stated reason.** Non-negotiable, everywhere.

### 3.2 The deliverables page becomes an offer, not a directory

- **Two tiers, unmistakably.** The four client-ready artifacts get the top of the
  page with real presence and a **rendered** excerpt. Analysis and raw collection
  drop to a compact secondary tier — a list, not cards.
- **Rendered samples.** Every excerpt renders as it will appear in the report,
  never as markdown source. This is the highest-value single change on the page.
- **Filenames become metadata** — small, secondary, beside a download control
  rather than in the headline position.
- **Actions become controls** with hover, focus and active states.

### 3.3 A print path

A report a client sees will be printed or PDF'd. A `@media print` stylesheet that
drops the app chrome and sets the document properly costs little and is the
difference between "a web page someone printed" and "a document".

## 4. Build order

1. Markdown → styled HTML rendering that covers headings, tables, emphasis,
   blockquotes and code, mapped onto Vi type tokens. This is what kills the
   raw-syntax problem at the root, in one place.
2. The report view: title block, findings, figure, tables, appendix.
3. The deliverables page: two tiers, rendered excerpts, controls.
4. Print stylesheet.
5. Cross-link both ways so nothing is a dead end.

## 5. Test plan

Everything below is a test, not a manual check.

- **Rendering:** no raw markdown escapes to the page — assert no `**`, no `##`,
  no `|---|` in any rendered surface. This is the regression that produced the
  complaint, so it gets a test that names it.
- **Report structure:** title block present; every corroborated finding carries a
  confidence badge; every citation resolves to an appendix anchor **that exists**;
  the appendix links back.
- **Tiering:** the four client-ready artifacts appear in the primary tier and the
  six others do not.
- **Samples render:** each deliverable's excerpt appears as markup, not source.
- **`None` handling:** a theme with no comparable stance still shows its reason,
  never `0` or blank.
- **Link crawl in both storage modes**, zero dead ends — the existing crawler,
  extended to the new surfaces.
- **Print stylesheet** exists and hides nav and controls.
- **Accessibility:** every control reachable by keyboard with a visible focus
  ring; tables have captions and scoped headers.

Plus the whole suite green — 398 before this work.

## 6. Deploy plan

1. Full suite green locally.
2. Local server: walk the report and deliverables screens at 1440 and 375.
3. Push to `build/vi-signal-mine-v1` and `deploy`.
4. `vercel --prod`. Blob storage now makes the deployment durable, so it should
   come up **read-write** — confirm the mutating routes no longer 409 and that a
   topic created on one request is readable on the next.
5. Independent crawl of production: zero broken links.
6. Confirm no raw markdown on any production page.

## 7. Out of scope, deliberately

- The clinician–patient gap will read `NE` on many themes while the deployment is
  offline, because no stance classifier runs without an Anthropic key. That is
  honest, not a defect, and adding keys fixes it.
- Adding your API keys. Yours to do; I will not handle your secrets.
- Vercel Postgres — its provisioning API is retired and Blob replaces it.
