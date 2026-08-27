# Tool elements

What the product does, who uses it, and every capability and state that has to
live somewhere in an interface. Companion to `BACKEND-ELEMENTS.md`, which
carries the data model.

---

## 1. What it is

A tool that watches what is being said about a healthcare brand or product
online, and turns that into intelligence: aggregated, weighted by how many
independent sources support it, split by who is speaking, and measured against
the same topic a week earlier.

Category neighbours: social listening, brand monitoring, marketing-campaign
analytics. Comparable products — Brandwatch, Sprinklr, Talkwalker, Tastewise,
Meltwater — with one difference that matters commercially: **collection is a
commodity and nobody sells it.** What is sold is the transformation. This
product's specific claim is provenance: every figure traces to a dated row with
a URL.

## 2. Who uses it

- **Operator**: a data analyst at a desk on a laptop, running real API calls
  that cost real money from a shared account. They are producing something they
  will hand to a client.
- **Recipient**: a commercial lead at a pharma client. Never touches the tool.
  Receives its output, in a meeting or as a file.

Two audiences, one of whom never sees the interface but sees the artifacts.

## 3. The core loop

1. **Define a topic** — name required; brand, molecule, competitors,
   therapeutic area, questions, forbidden terms all optional.
2. **Confirm the spend** — an itemised estimate against a hard cap. Real money
   on a shared account.
3. **MINE** — collect a dated snapshot.
4. **INSIGHT** — seven passes: entity resolution, corroboration, theme
   clustering, stance, the clinician-vs-patient split, momentum against prior
   snapshots, anomaly detection.
5. **REPORT** — four documents, one of them client-deliverable.

Steps 3–5 are independently runnable and chainable. A topic is swept repeatedly;
history is the point, because momentum needs a baseline.

## 4. Capabilities that must be reachable

**Topic**: create, edit, delete (with its runs and artifacts), list, search,
sort, filter.
**Run**: start a mine at a chosen band, start an insight from a snapshot, start
a report from an insight, view any run, download any artifact.
**Cross-cutting**: see cost before committing, see cost after, trace any figure
to its rows, compare a snapshot to the one before it.

## 5. States that carry more weight than the happy path

Each is a real state with distinct meaning. Collapsing any two is a defect.

| State | Why it matters |
|---|---|
| No prior snapshot | Momentum and anomaly are undefined, not zero |
| Only one audience discussed a theme | No gap exists. Silence is not agreement |
| Stopped on budget | A successful partial. Rows are kept |
| A guard blocked the output | An uncitable claim, a forecast, a forbidden term |
| A venue returned nothing | Must be named — a silent filter looks like an empty world |
| Data is fabricated | The offline demo miner ran. Must be unmissable and must follow the file out of the tool |
| Storage cannot persist | Writes would be accepted and lost. The tool refuses instead |
| Topic defined, never run | Nothing collected |
| Collected, never analysed | Signals exist, no findings |
| One snapshot only | Analysable, but no trend is possible |

## 6. Vocabulary that currently leaks

Internal terms a user should not have to learn. **All are open to renaming.**

| Current | What it means |
|---|---|
| `corroborated` | Three or more independent sources support this. Safe to state |
| `emerging` | Two sources. Not yet safe to state |
| `single_source` | One source |
| `NE` / `not estimable` | The two audiences cannot be compared here |
| `probe` / `standard` / `deep` band | How wide and how expensive the sweep is |
| `tier` (confidence) | How well-supported a finding is |
| `tier` (collection A/B/C) | *A different thing.* How a venue may legally be collected. **Two unrelated meanings share one word** |
| `dual-lens` | Clinician view vs patient view |
| `signal` | One collected post or page |
| `snapshot` | One dated collection run |
| `momentum` | Change against the previous snapshot |
| `venue` | A website that was collected from |
| `kind` | What type of site a venue is |

## 7. Interface surfaces that exist today

Landing overview · topics list · new/edit topic form · topic detail · spend
confirmation · run detail · snapshot view · insight view · report view ·
deliverables catalogue · how-it-works · delete confirmation · error pages.

## 8. Volume and pacing

- A sweep takes seconds to a minute. Not real time; no live updating needed.
- A topic is swept on the order of weekly.
- Reading is far more common than writing. Most sessions are "what changed?"
- Numbers are small: tens of themes, hundreds of signals. This is **not** a
  big-data dashboard, and pretending otherwise would be dishonest.

## 9. Hard constraints

- Server-rendered HTML, **no JavaScript required**, no build step
- No CDN, no external fonts, no external network of any kind
- Renders offline
- Must print — the report is handed over, sometimes on paper
- Accessible: WCAG 2.2 AA, keyboard-navigable, screen-reader-navigable
- Deployed on serverless with a 60-second request ceiling

## 10. Known failures of the current interface

The brief that produced this document, verbatim from the owner:

> "The UI itself is trash. Both the UX. Too wordy, hard to navigate, hard to
> understand what's there and what does it even mean. Language super vague and
> not clear. It's supposed to be insightful and dashboardy and it became a word
> laundering shit. It still looks like an Excel in HTML plus AI slop messages
> which nobody will read."

Measured, to make that concrete:

- The report page: **1,828 words for 180 figures**. Confirming a spend took
  **711 words**.
- **24–41% of every page** was explanatory prose rather than content.
- One block of ~300 words appeared on **five separate screens**.
- One warning repeated **ten times on a single page**.
- After one pass of cutting, the app is still **4,545 words** across nine
  screens, and every screen is still fundamentally a table.

Two diagnoses the owner named directly:

1. **"Excel in HTML"** — nearly every screen is a `<table>`. There is almost no
   visual encoding: no charts, no proportion, no shape. A reader has to compute
   the meaning from digits.
2. **"AI slop nobody will read"** — the prose explains, hedges and repeats. It
   reads as generated. Where a number could carry a fact, a sentence describes
   the number instead.

## 11. What the design work must produce

An interface where:
- the answer is visible before any prose is read
- quantity is *seen*, not parsed from digits
- a user never has to learn an internal word to understand a screen
- the ten states in §5 stay distinguishable — this is not licence to simplify
  a null into a zero
- it still works with no JavaScript, offline, and on paper

## 12. Visual language

The interface must ultimately be expressed in the Vi marketing design system:
white canvas, black structure, a single violet accent (`#4F31F5`) used
sparingly, 0.5px hairlines, Neue Montreal.

**This is applied last.** The design work should be done in whatever visual
terms serve the product best; translation into Vi's language is a later,
separate step, and should not constrain the structural thinking.
