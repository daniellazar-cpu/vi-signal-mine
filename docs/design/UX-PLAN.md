# UX plan

Structural and typographic design for the tool described in `TOOL-ELEMENTS.md`
and `BACKEND-ELEMENTS.md`. No visual identity is applied here; that is a later,
separate pass.

---

## 0. The one decision everything else follows from

**This is not a dashboard. It is a briefing document that updates weekly.**

Every product in the category — Brandwatch, Sprinklr, Talkwalker, Meltwater —
is built as a dashboard because their data streams continuously and the user's
job is to monitor. Neither is true here:

- Data arrives in discrete dated sweeps, on the order of weekly (§8).
- Nothing updates live; a sweep takes under a minute and then stops (§8).
- The output is handed to someone who never opens the tool (§2).
- It must print (§9).
- There is no JavaScript (§9).

Designing it as a dashboard is what produced "Excel in HTML": dashboard layouts
demand density, density without interaction collapses into tables, and tables of
digits need prose to explain them. Designing it as a **document** — sectioned,
sequential, printable, with figures and margin citations — resolves the print
constraint, the no-JS constraint, the deliverable constraint and the provenance
claim in one move. Screens become pages. The client deliverable becomes those
pages printed, not a separately written essay that can drift from them.

Two structural consequences, applied throughout:

1. **The evidence rail.** Every page is two zones: a wide content column and a
   narrow right-hand rail. Every figure, bar and claim in the content column has
   a matching rail entry: `n`, sweep date, source count, link to the rows. On
   print the rail becomes scholarly sidenotes. This makes the commercial claim —
   *every figure traces to a dated row with a URL* — a structural property of
   the layout rather than a sentence somebody has to write.
2. **One leaf.** Every number on every page links to the same destination: a
   filtered list of the collected rows behind it. Nine screens, one drill target.

---

## 1. Category conventions

### What mature products actually do

**Object model.** Brandwatch hangs everything off a *Query*; Sprinklr off a
*Listening Topic*; Meltwater off a *Saved Search*; Amplitude and Mixpanel off a
*saved Chart* inside a *Board*. In all of them one persistent named object owns
all history and all views. This product already has that object: the Topic. It
should be the only thing in global navigation.

**Screen taxonomy.** The recurring three-tier shape is
`list of objects → object overview → atomic row list`. GA4 formalises the middle
tier's anatomy: **scorecard row → chart → table**, in that order, top to bottom,
on every canned report. That ordering is the single most useful convention
available here and should be adopted literally.

**"What changed" views.** Talkwalker's Overview, Amplitude's anomaly detection,
GA4's Insights cards and Sprinklr's Smart Alerts converge on the same
construction, and it is not a chart:

> a **ranked list of discrete change events**, each stating (a) what,
> (b) direction, (c) magnitude, (d) the baseline it is measured against, and
> (e) a link to the evidence.

The chart is for the drill-down, not the summary. Adopt this exactly.
Talkwalker's second convention — the comparison to the previous equal-length
period is always on, never an option — should also be adopted, with the
period replaced by the previous sweep.

**Drill-down.** Universal: aggregate → filtered atomic list → source. Amplitude
and Mixpanel add the part most tools get wrong — the active filter set is
rendered as **removable chips above the list**, so you always know what subset
you are looking at. Adopt.

**Provenance.** Amplitude keeps a definition panel one click from every chart
showing exactly what was measured. Here that is not a nicety, it is the product.
Promote it from a panel to the persistent evidence rail.

**Suppression.** Mixpanel greys or withholds results below a sample threshold.
With 10–500 rows split across 3–15 themes, some cells will be `n=2`. Adopt a
hard suppression rule (§4).

**Cost.** No listening tool shows per-run cost, because collection is free to
their user. Borrow instead from cloud consoles (AWS Billing, OpenAI usage): a
**spend-against-cap meter** with a tick at the estimate and a hard rule at the
cap.

### What to reject, and why

| Convention | Reject because |
|---|---|
| Freeform explorer / query builder (GA4 Explore, Amplitude chart builder, Brandwatch boolean editor as a primary surface) | 3–15 themes and 10–500 rows. Slicing that seven ways is theatre, and it needs JavaScript. |
| Configurable dashboards of draggable cards (Brandwatch components, Mixpanel Boards) | One operator, one deliverable shape, no JS to drag with. A fixed opinionated layout also lets the deliverable be a direct print of the screen. |
| A global continuous date-range picker | **The time axis here is discrete, not continuous.** "Last 30 days" is unanswerable; what exists is the sweep of 12 Aug and the sweep of 19 Aug. A range picker would promise interpolation the data cannot support. Replace with a **sweep selector**: two slots, *showing* and *compared with*. |
| Sentiment-over-time line charts as the hero | 3–60 points, often 1. §8 says pretending this is big data would be dishonest. |
| Share of voice, reach, impressions, "buzz score" | Not in the data model. Inventing them breaks provenance. |
| Tastewise-style predicted growth curves | G5 forbids forecasting. |
| AI-generated narrative summary cards (GA4 Insights, Brandwatch Iris, Sprinklr summaries) | This *is* the "word laundering" the owner named. Prose belongs in the deliverable documents, not on screens. |
| A separate "Alerts" surface | Weekly cadence. The change list on the topic page is the alert. |

---

## 2. Screen inventory

Thirteen surfaces become **nine**, of which six are read surfaces.

Navigation: one global rail with two items — `Topics` and the current topic's
name. Within a topic, a five-item sub-rail: **Change · Findings · Evidence ·
Collection · Files**. Theme pages are drilled into, never navigated to. No
sidebar; a sidebar for nine pages is overhead.

Global context control on every topic screen: the **sweep axis** — a horizontal
date line with one tick per sweep, spaced by real elapsed time so gaps in
cadence are visible. Each tick is an anchor carrying `?as_of=`; a second row of
anchors sets `?vs=`. No JavaScript. Selecting a sweep re-renders Change,
Findings and Collection as of that date. This is why there is no separate "run
detail" screen.

---

### 1. Watchlist — `/`
**Question:** which topics moved, and which need attention?

In order: topic name · volume sparkline across sweeps (date-spaced) · change
mark vs previous sweep · last-swept date and its age · state chip · cumulative
spend. Sort and filter are anchors.

**Not on it:** themes, findings, cost breakdown, any prose, "recently viewed",
any onboarding. Replaces the old landing overview *and* topics list — in every
comparable product the landing page is a redundant restatement of the list.

### 2. Topic — Change — `/t/{id}`
**Question:** what changed since the previous sweep?
Default landing for a topic. The money screen.

1. **Sweep header** — four large figures: mentions collected, themes, findings
   that clear 3 sources, spend. Plus the three-step strip
   `Collected ✓ · Analysed ✓ · Report —` and the date being compared against.
2. **Change list** — `anomaly.json` merged with `momentum.json`, deduped,
   appeared/vanished first, then by |magnitude|. Each row: theme · before→after
   mini bars · signed delta · ≤12-word reason · evidence link. **Capped at seven
   rows** plus "n more" — a summary longer than seven is not a summary.
3. **All themes** — bullet bars with a prior-value tick, sorted by volume.
4. **Clinicians vs patients** — dumbbells; one-audience themes in their own
   labelled group below (§7.2).
5. **Who and what got named** — entity bar list, top 10 from `entities.json`.
6. **Collection health** — the 40-cell coverage strip and spend meter, small,
   linking to Collection.

**Not on it:** individual mentions, finding statements, methodology, the venue
registry, cost breakdown, run notes.

### 3. Topic — Findings — `/t/{id}/findings`
**Question:** what can I say, and how well is it sourced?

1. The topic's `questions`, each with a count of findings that bear on it.
   Unanswered questions are stated as unanswered — this is the operator's actual
   job and no comparable product does it.
2. Findings grouped by source count: **3+ / 2 / 1**. Group heading carries the
   count and, once, the independence rule.
3. Each finding: the `statement` set as the largest text on the page — it is the
   product — then pips + count, theme chip, the list of sites backing it, an
   evidence link, and any `unresolved_ids` marked.

**Not on it:** charts, momentum, cost, the venue registry, methodology.

### 4. Theme — `/t/{id}/theme/{theme_id}`
**Question:** everything about this one theme.

Volume and its change · sentiment mix · clinicians vs patients with net
positions · site-type mix · the findings that draw on it · a link to its
mentions. One page per theme; 3–15 of them.

**Not on it:** other themes, cost, coverage.

### 5. Evidence — `/t/{id}/evidence?…`
**Question:** show me the rows behind that number. **The single leaf.**

Active filter chips (theme, audience, sweep, site, sentiment), each removable by
anchor · the count, large · then a table: date · excerpt (widest column) · site
and type · who's speaking with a confidence pip · sentiment · names the brand? ·
outbound link. Column headers are sort anchors.

**Not on it:** any aggregate, any chart, any prose.

### 6. Topic — Collection — `/t/{id}/collection`
**Question:** what did we reach, what did we miss, what did it cost?

Sweep status and spend meter · coverage strip with the empty and blocked sites
**named** · cost breakdown table · data-quality figures (share with a resolved
speaker type, entity match rate, duplicates removed, access-basis mix) · the six
guards with pass/blocked and detail.

**Not on it:** themes, findings, sentiment.

### 7. Start a sweep — `/t/{id}/run`
**Question:** am I allowed to spend this?

Three size choices as cards, each with a cost bar and the itemised estimate ·
the cap · **one** sentence of consequence · confirm. ≤60 words total, down from
711.

**Not on it:** what mining is, how the passes work, reassurance, a progress
narrative.

### 8. Topic setup — `/t/new`, `/t/{id}/edit`
Single column. `name` is the only required field and is visually dominant;
everything else sits in one optional group with no accordion and no section
intros. Delete lives at the bottom, gated by typing the topic name, and states
what will be destroyed as counts.

### 9. Files — `/t/{id}/files`
A manifest: artifact · sweep · generated · size · download. Demo-prefixed when
synthetic. Legitimately a table.

**Utility:** a genuine 404/500. Nothing else. Blocked guards, empty venues and
missing analysis all render **in place**, at the size the content would have
occupied — an error page throws away the valid nine tenths of the result.

---

## 3. Vocabulary replacement

### The word collisions that must not survive

**"tier"** carries two unrelated meanings and **"band"** carries two more. Both
words are banned outright from the interface.

| Word | Meaning A | Meaning B | Resolution |
|---|---|---|---|
| `tier` | how well-supported a finding is | how a site may legally be collected | A → **"sources"** (a count, not a category). B → **"access basis"**. The word `tier` appears nowhere. |
| `band` | `spend_band`: how wide/expensive the sweep is | venue band 1/2/3: conversation / opinion / substrate | A → **"sweep size"**. B → **"content type"** (Talk / Opinion / Reference). The word `band` appears nowhere. |

### The full table

| Internal | Interface term | Note |
|---|---|---|
| `signal` | **mention** | Category-standard (Brandwatch, Meltwater, Talkwalker). |
| `brand_mentioned` | **names the brand** | Renamed to clear the collision with "mention". |
| `snapshot` / a MINE run | **sweep**, always attached to its date | The object in the UI is "19 Aug", not an abstraction. |
| `corroborated` | **3+ sources** · pips ●●● | The count *is* the label. No invented category word. |
| `emerging` | **2 sources** · ●●○ | |
| `single_source` | **1 source** · ●○○ | |
| `independent_sources` | **sources** | Rule stated once, at the group heading: *"One forum post = one source. One publisher = one source, however many pages it runs."* |
| `tier` (confidence) | *deleted* | Superseded by the count above. |
| the confidence consequence | legend, stated once: *"3+: safe to state as-is. 2: attribute it. 1: quote it, don't generalise."* | Advisory, per G2. |
| `NE` / `not estimable` | **"Only clinicians discussed this"** / **"Only patients discussed this"** | Name the fact; never use a status token. Compact form: *"No comparison — one audience only"*. |
| `divergence` | **gap between clinicians and patients** | |
| `hcp_net` / `patient_net` | **clinician tone** / **patient tone** | |
| `dual-lens` | **clinicians vs patients** | |
| `spend_band: probe / standard / deep` | **Narrow / Standard / Wide**, cost always adjacent | Glossed once: *"how many queries and page fetches"*. |
| `collection_tier` A / B / C | **access basis**, values spelled as words | Never a bare letter. See open question Q1. |
| `collection_method` | **how we got it**: Site's own API / Search result / Public page | |
| `momentum` | **change since 12 Aug** | Always name the baseline date. The word never appears. |
| `venue` | **site** | |
| `kind` | **type of site** | `evidence`→Published evidence · `guideline_body`→Guideline body · `hcp_discussion`→Clinician forum · `patient_community`→Patient community · `regulatory`→Regulator · `drug_reference`→Drug reference |
| `stance` | **sentiment** | The word a pharma marketer already owns. |
| `unclear` (stance) | **couldn't tell** | Always rendered last and unfilled, so it never reads as an opinion. |
| `author_type` | **who's speaking** | `hcp`→Clinician · `patient`→Patient · `institutional`→Organisation · `unknown`→**not identified** (a gap, not a value). |
| `mode: mine / insight / report` | **Collect / Analyse / Report** | Verbs, used only in the three-step strip. |
| `run` | *mostly deleted* | Becomes the three-step strip on a sweep. |
| `status: stopped_on_budget` | **stopped at the cap — kept 143 mentions** | Belongs to the *complete* family, never the *failed* family. |
| `synthetic` | **demo data — not real** | |
| `never_say` | **words we must not print** | |
| `anomaly.kind` | `theme_appeared`→**new this sweep** · `theme_vanished`→**gone this sweep** · `volume_spike`→**sharp rise** · `volume_collapse`→**sharp drop** | |
| `venues_empty` | **returned nothing** | |
| `venues_restricted` | **blocked us** | |
| `unmapped_mentions` | **names we couldn't match** | |
| `theme`, `finding`, `sentiment`, `cap`, `estimate` | unchanged | Already plain. |

---

## 4. Visual encoding

Everything below is inline SVG or plain CSS, server-rendered, no JavaScript, no
external assets. Two non-negotiables:

- **Colour is never the only channel.** Every encoding also uses length,
  position, fill pattern (SVG `<pattern>`) or text. It has to survive greyscale
  print and WCAG 2.2 AA.
- **Every graphic carries its number.** `role="img"` plus `<title>`/`<desc>`,
  wrapped in `<figure>`/`<figcaption>`, with the value also present as text.
  A screen reader must never depend on the shape.

| Data | Encoding | Why |
|---|---|---|
| Theme volume (3–15 themes) | **Horizontal bar list**, sorted descending, label left, count at bar end | Ranking plus magnitude in one pass. Never a pie — 15 categories is unreadable as angle. |
| Change vs prior sweep | **Bullet bar** (Few): one solid bar for now, a vertical tick where it stood last sweep | One row shows level *and* change. Direction repeated as ▲/▼ plus a signed number, so colour is redundant. |
| Volume across sweeps | **Inline SVG sparkline with visible dots**, points spaced by real date | 1 point = a single dot with its value. 2 points = two dots and a rule. ≥3 = polyline with dots. A smooth curve through two points is a chart of nothing. Even spacing would misstate cadence. |
| Sentiment mix per theme | **100% stacked bar**, five patterned segments in fixed order: Positive, Mixed, Neutral, Negative, Couldn't tell | Fixed order makes rows comparable at a glance. "Couldn't tell" is unfilled and always last. `n` printed adjacent — a 100% bar without a denominator is a lie. |
| — suppression rule | **Below n=5, do not draw the proportional bar.** Print the raw counts as pips instead | A proportion of three rows is noise dressed as a measurement (Mixpanel's threshold convention). |
| Clinicians vs patients | **Dumbbell** on a shared −1…+1 axis: one dot per audience, connected. The connector's length *is* the gap | The most direct possible encoding of divergence, and it degrades honestly to a single dot when only one audience spoke (§7.2). |
| Source count per finding | **Three pips** ●●● / ●●○ / ●○○ plus the literal number ("●●● 7") | Ordinal, tiny, printable, no colour. |
| Coverage across ~40 sites | **Unit strip**: one cell per site, in one row. Solid = returned rows · outline = returned nothing · hatched = blocked us · absent = not tried | 40 cells fits one line and replaces a 40-row table. Four states, four distinct fills, no colour dependency. Empty and blocked sites are *also* named in text below — required by §5. |
| Spend | **Meter bar**: fill = spent, tick = estimate, hard rule = cap. When stopped, the fill terminates in a stop-bar glyph | Cloud-console convention. Makes "stopped at cap" a visible shape, not a status word. |
| Spend across sweeps | Small bars on the **same date axis as the volume sparkline** | Answers "are we paying more for less?" without a new screen. |
| Site-type mix per theme | **Dot-size grid**: themes × 6 site types, dot area ∝ count, number printed beside | A heat grid would need colour. Area plus a printed number works in greyscale and at n=1. |
| Engagement (`upvotes`, `replies`) | Two counts with a bar proportional to the max in view. Absent → **"not reported"** | Free-shape and often missing; must never render 0. |
| Sweep cadence | **Date axis with one tick per sweep**, real spacing | Doubles as the navigation control. A missed week is visible as a gap. |
| Anomalies | **Not a chart.** A ranked list of events, each with a before→after pair of mini bars | `theme_appeared` has no baseline: the prior slot is empty and captioned "not present on 12 Aug". Never a zero-height bar. |
| Author-type confidence | A **pip**, not a decimal | 0.73 implies a precision nobody can act on. |

### Typography as the primary encoding

With no colour system yet, weight and size carry hierarchy. Ratios to body:

| Step | Ratio | Use |
|---|---|---|
| `figure-xl` | 3.0, bold, `tabular-nums` | The one number that answers the screen |
| `figure` | 1.8, medium, `tabular-nums` | Scorecard values |
| `title` | 1.5 | Screen title |
| `section` | 1.15, bold | Section heads |
| `body` | 1.0 | Finding statements, excerpts |
| `meta` | 0.85 | Evidence rail, provenance, deltas |

`font-variant-numeric: tabular-nums` everywhere a number can be compared
vertically. Deltas are set at `meta`, never at figure size — a delta is never
more important than the level it modifies.

**Rule of area:** on any read screen, the encoding blocks must occupy at least
twice the area of the label and chrome blocks. If they do not, the screen has
reverted to a table.

### Where a table is genuinely right

A table is correct when the task is **lookup or export**, and wrong when the
task is **comparison**. These stay tables:

- **The Evidence leaf.** Many heterogeneous rows the user scans and clicks out
  of. Give the excerpt the most width; it is the content.
- **The cost breakdown** (`breakdown[]`). Itemised money. Tables are what
  invoices are.
- **The site registry** (~40 rows, ToS and robots text). Reference lookup.
- **The files manifest.** Filename, date, size, link.
- **The provenance appendix** — claim → mention ids → URLs. This is the
  product's proof and its tabular form is the point.

Nothing else is a table.

---

## 5. Copy rules

Current: **4,545 words across nine screens** (~505 each). Target: **under 900
words for the whole read side.**

### Budget per screen

| Screen | Budget (chrome + explanatory text; data values excluded) |
|---|---|
| Watchlist | 40 |
| Change | 120, including all generated `reason` strings |
| Findings | 60 chrome. Statements are content, capped at **25 words each** |
| Theme | 80 chrome; each `reason` ≤15 words |
| Evidence | 30. Excerpts are data, capped at ~200 characters + link |
| Collection | 100, most of it the named site lists, which are data |
| Start a sweep | 60 (was 711) |
| Topic setup | Field labels + ≤8-word helper, **only** on `never_say`, `competitors`, `questions` |
| Files | 25 |

Enforce it: a build-time test that counts rendered words per template and fails
over budget. Unchecked budgets are aspirations.

### What earns a sentence

Exhaustively. Anything not on this list is a number or a label.

1. A consequence involving money or irreversibility.
2. A statement of fact that *is* the product's output — a finding's `statement`.
3. A named cause when the state is not the happy path: why a site returned
   nothing, which guard blocked and on what.
4. A definition that would otherwise be guessed — stated **once per
   application**, at first point of use, ≤20 words.
5. An empty state that must disambiguate between several possible truths.

### What must never be a sentence

- **Anything that describes a number already on screen.** "Volume increased by
  12%, a moderate rise" restates the figure and adds an unsourced judgement.
  This single rule removes most of the 4,545 words.
- Reassurance, hedging, or capability description ("uses seven passes to…").
- Instructions for reading a chart. If a chart needs instructions, redraw it.
- Section introductions.
- **Repeated warnings.** *A warning appears once, at the highest scope at which
  it is true.* Synthetic data is one banner per page plus one mark per exported
  file — not one per row. That is what turned into the warning printed ten
  times on one page.
- The second person, outside forms and confirmations.

**Banned words:** insights, leverage, comprehensive, robust, powerful,
seamlessly, actionable, deep dive, holistic, "it's important to note", "please
note", "this section", "as you can see", "helps you", "enables", "in order to".

### Empty states

An empty state names **which** of the possible truths holds, and offers one
action. Template: `[Fact]. [Cause if known]. → [one link]`, ≤12 words plus the
link. A generic "No data" is a defect, because at least five different facts
produce an empty region on this product.

| Region | Empty state |
|---|---|
| Change, first sweep | "First sweep — nothing to compare with yet." |
| Change, nothing moved | "No theme moved. 11 themes, same as 12 Aug." |
| Change, not analysed | "143 mentions collected 19 Aug. Not analysed. → Analyse" |
| Change, never collected | "Nothing collected. → Start the first sweep" |
| Findings, none clear 3 sources | "No finding reached 3 sources. 6 reached 2." |
| A question with no bearing findings | "No mention bears on this question." |
| Coverage, a site returned nothing | "Returned nothing (6): a.com, b.org, …" |
| Evidence, filtered to nothing | "No mention matches these 3 filters. → Clear site" |

### Numbers

- Tabular figures; no more precision than the source supports.
- **Percentages only at n ≥ 20.** Below that, raw counts. "67% negative" from
  three rows is a false statement.
- Every delta carries a sign and its baseline date.
- Money: cents below $10, whole dollars above.
- A null is a **word**. A zero is a **numeral**. Neither is ever a dash.
  Reserve `—` for "this field does not apply to this row type", and prefer a
  word even then.

---

## 6. Information hierarchy per screen

Eye order, with relative weight.

**Watchlist.** 1st: the sparkline column — shape is scannable at 200 rows where
digits are not. 2nd: the topic name at `body` weight bold. 3rd: the state chip.
Spend and dates recede to `meta`. Nothing is at `figure` size; no single topic
should out-shout the list.

**Change.** 1st: the sweep header's four `figure` values, with mentions
collected at `figure-xl` — the reader's first question is "did anything come
back". 2nd: the change list, whose left edge of theme names forms the strongest
vertical in the page. 3rd: the all-themes bar list, where the bar mass is the
visual weight and the labels are `meta`. Clinicians-vs-patients, entities and
the health strip descend in size down the page. The health strip is deliberately
the smallest thing on the screen — it is a link, not a report.

**Findings.** 1st: the question list, set at `section` — it frames everything
under it. 2nd: the group heading "3+ sources (4)" at `section`. 3rd: the finding
`statement` at `body`, but given the full measure of the column and generous
leading, so it reads as prose and dominates by area. Pips, sites and links sit
at `meta` in the evidence rail, never inline in the statement. The statement is
the only thing on the page allowed to be a paragraph.

**Theme.** 1st: theme name at `title` with volume at `figure-xl` immediately
beneath. 2nd: the dumbbell — the audience split is the theme's most decision-
relevant fact. 3rd: the sentiment bar. Site mix and the finding list are `meta`.

**Evidence.** 1st: the count at `figure-xl`, because it is the number the reader
arrived to verify. 2nd: the filter chips, which must be unmissable or the reader
will misread a subset as the whole. 3rd: the excerpt column. Date, site and
speaker are `meta`. No graphic anywhere on this page.

**Collection.** 1st: the spend meter, at full column width — real money on a
shared account. 2nd: the coverage strip. 3rd: the named lists of sites that
returned nothing or blocked us. The breakdown table and guard results are `meta`
and sit below the fold by design.

**Start a sweep.** 1st: the three cost bars, drawn to the same scale so the
choice is a comparison of lengths, not of words. 2nd: the cap, stated as a
figure. 3rd: the one consequence sentence. The confirm control is last in
reading order and last in the DOM.

**Topic setup.** 1st: the name field, at `title` size in the input itself. 2nd:
the optional group. 3rd: delete, at `meta`, at the bottom, behind typing the
name.

**Files.** Flat by design. A manifest has no hierarchy; imposing one would
imply a recommendation.

---

## 7. The ten states

A correctness requirement. For each: how it renders, and what it must not be
confused with.

**7.1 No prior snapshot.** Comparison slots are *present but marked*. Every
bullet bar renders without a prior tick. The delta position reads **"first
sweep"** in words — never `—`, never `0%`, never `+100%`. The change list is
replaced by one line: "Change needs two sweeps. This is the first." The sweep
axis shows one tick.
*Must not look like:* nothing changed.

**7.2 Only one audience discussed a theme.** The dumbbell draws **one filled dot
and no connector**; the absent audience's position is an empty slot captioned
with which audience is missing. The gap value reads "not comparable — patients
didn't discuss this". These themes are additionally **sorted into their own
group** at the foot of the clinicians-vs-patients block, headed "Discussed by
one audience only (n)", so they can never be visually averaged into the
comparison above.
*Must not look like:* a gap of zero, or agreement. This is the system's
highest-risk null.

**7.3 Stopped on budget.** The meter fill reaches the cap and terminates in a
stop-bar glyph. The chip reads "Stopped at cap — kept 143 mentions" and belongs
to the **complete** visual family (solid), not the failed family. A single
dagger `†` on the sweep header, once, means "collection was cut short at the
cap"; it is not repeated on every derived figure.
*Must not look like:* a failure, or a complete and exhaustive sweep.

**7.4 A guard blocked the output.** The blocked artifact renders **in place, at
the size the content would have occupied**, as a struck panel naming the guard
and the trigger: "Blocked: a claim carried no citation (G1)." Everything else on
the page still renders. Never a redirect to an error screen — the rest of the
result is valid and the operator needs it.
*Must not look like:* a missing section, a system error, or an empty result.

**7.5 A venue returned nothing.** In the coverage strip, an **outlined** cell —
visually distinct from hatched (blocked us) and from absent (not tried). Below
the strip, the sites are **named** in a list. Three separate lists, three
separate counts.
*Must not look like:* a site that was never tried, a site that refused us, or an
empty world.

**7.6 Data is fabricated.** A full-width bar at the top of every page of that
topic: "Demo data. Not real." Every figure derived from it sits inside a
ruled/hatched container border, so the mark survives a screenshot of one chart.
`DEMO` appears in the running head of every printed page, prefixed on every
downloaded filename, and written into the first line of every exported file.
One banner per page, never one per row.
*Must not look like:* real data with a footnote.

**7.7 Storage cannot persist.** A system bar above everything, including the
demo banner. Every write control renders **disabled with its reason inline** —
"Storage unavailable; nothing would be saved" — rather than accepting input that
will be lost. Read views continue to serve whatever can be read.
*Must not look like:* a transient error, or a successful save.

**7.8 Topic defined, never run.** The topic renders its full shell — Change,
Findings, Collection all present — each section carrying its own specific empty
state. **Start the first sweep** is the visually dominant element on the page,
the only thing at `figure` weight. The sweep axis is an empty line with the
created date marked.
*Must not look like:* a topic that was swept and found nothing.

**7.9 Collected, never analysed.** Collection is fully populated — counts,
coverage strip, cost, guards. Change and Findings read "143 mentions collected
19 Aug. Not analysed. → Analyse". The mention count must appear in the empty
state itself, so it is immediately obvious that data exists.
*Must not look like:* nothing collected.

**7.10 One snapshot only.** Findings, themes and sentiment are fully populated;
only the change surfaces degrade, exactly as 7.1. The `vs` selector slot renders
"nothing earlier" rather than being hidden — a hidden control implies the
comparison is unavailable for some other reason. **7.1 and 7.10 are the same
visual treatment at two scopes**: 7.1 is a property of a figure, 7.10 a property
of the topic. Saying so in the code prevents two divergent implementations.

### Cross-cutting rules

- **Four run statuses, four non-colour treatments:** running = outlined + "started 14:22";
  complete = solid; stopped at cap = solid + terminal stop bar; failed =
  cross-hatched + struck.
- **A null renders as a word; a zero renders as a numeral.** No dashes for
  either. This is testable and should be a test.
- Any figure that could be either must be rendered by a single shared helper, so
  the rule cannot be forgotten in one template.

---

## 8. What to cut

1. **The how-it-works screen.** This is where the ~300-word block that appeared
   on five screens lives. Methodology already ships to the client as
   `methodology.md`. Replace with definitions stated once at first point of use
   and one footer link.
2. **The landing overview** as distinct from the topics list. It is a
   restatement. Merge into Watchlist.
3. **The run detail screen.** A run becomes a three-step strip on a sweep;
   mechanical detail lives on Collection; failures render in place.
4. **The delete confirmation screen.** Inline on the edit page, gated by typing
   the topic name — fewer navigations *and* a stronger guard than a page with a
   red button.
5. **Standalone error pages**, other than a real 404/500. Guard blocks, empty
   venues and missing analysis render in place. An error page discards the valid
   remainder of the result, which is precisely what this product's partials are.
6. **The deliverables catalogue** as a browsing surface. Reduce to a manifest.
7. **`pulse_report.md` as separately authored prose.** This is the largest cut
   available and the most opinionated. The client deliverable should be the
   Findings, Themes and Provenance pages printed via `@media print` — not an
   essay written alongside them. Reasons: it removes the single biggest word
   count in the system (1,828 words for 180 figures); it makes it structurally
   impossible for the deliverable and the screen to disagree; and it forces the
   screens to be good enough to hand over, which is the actual goal.
   *If the prose report survives*, cap it at 400 words and forbid it from
   restating any figure that appears in a printed figure on the same page.
8. **Per-figure explanatory captions.** One definition per concept per app.
9. **`intent_score`, `action`, `distribution_mode`** from every screen. No
   artifact consumes them and the brief states no decision they change. Keep
   them in the JSON export. If someone can name the decision, they come back.
10. **`author_type_rationale` from list views.** It is per-row prose; 500 rows
    of it is 500 units of slop. Keep it on the single-mention view only.
11. **`author_type_confidence` as a decimal.** A pip.
12. **`entities.by_signal`** from the interface. Keep the entity bar list — "were
    competitors named" is a real commercial question — and keep
    `unmapped_mentions` as one count on Collection.
13. **Run `note`** from every read screen except Collection.
14. **The word "dashboard"** from how the team talks about this, per §0.

---

## 9. No-JavaScript mechanics

For the build, so none of the above quietly requires a script:

- Sweep selection, filtering, sorting: anchors carrying query parameters.
- Progressive disclosure: `<details>`/`<summary>`, forced open under
  `@media print`.
- All graphics: inline `<svg>` with `<pattern>` fills for greyscale
  differentiation; `role="img"`, `<title>`, `<desc>`; wrapped in
  `<figure>`/`<figcaption>`.
- Bars can be CSS (`width: 43%`) where a single rectangle suffices; SVG where
  there is an axis, a tick or multiple marks.
- The evidence rail: a CSS grid second column that reflows beneath each block at
  narrow widths and becomes a print margin note. No JS in either state.
- Print: `@page` margins, running head carrying topic + sweep date + DEMO when
  applicable, `break-inside: avoid` on every figure block.
- Everything renders inside the 60-second serverless ceiling because it is read
  from stored artifacts, not recomputed.

---

## 10. Open questions for engineering

Flagged rather than guessed, because the wording depends on facts not in the
briefs:

- **Q1.** Exact semantics of `collection_tier` A/B/C. "Access basis" needs three
  plain value strings and I will not invent what the terms permit.
- **Q2.** Semantics of venue band 1 (conversation) / 2 (opinion) / 3 (substrate).
  Proposed Talk / Opinion / Reference is a guess at intent.
- **Q3.** What `unresolved_ids` on a finding means — cited rows that could not be
  fetched, or rows that failed a check? The label differs.
- **Q4.** Whether `engagement` keys are stable beyond `{upvotes, replies}`. The
  encoding assumes two, with "not reported" for absent.
- **Q5.** Whether `intent_score`, `action` and `distribution_mode` drive any
  decision. Cut from the UI on the assumption they do not.
</content>
</invoke>

---

## 11. Answers to §10, from the code

Added after the plan was written. Four of the five are settled by the
implementation; one is a product decision and stays open.

**Q1 — `collection_tier` A/B/C.** Not a quality grade. It is *how a site may
lawfully be collected*, and it gates one specific action: **only a site a human
has classified A or B may have its page fetched.** Tier C is a named blocklist
(Doximity, Sermo, Medscape member areas, private social groups, Slack/Discord).
An unclassified site is usable as a search result but is never page-fetched, so
it is not silently promoted. Note the deliberate asymmetry the code records: by
decision D5 a Tier-C domain is *recorded rather than refused* when search
returns it, and the tier travels with the row so the choice stays visible.

Proposed value strings: **"Site's own API"** (A) · **"Public page"** (B) ·
**"Search result only — we don't fetch this site"** (C and unclassified).
"Access basis" is the right column name.

**Q2 — venue band 1/2/3.** Still open, and it is a product question rather than
a code one. The code's own gloss: 1 = what clinicians and patients *say*
(forums, communities); 2 = named clinicians and trade press publishing publicly;
3 = evidence, guidelines, labels — *the material an article is written from,
not the signal being mined*. **Talk / Opinion / Reference** carries that
faithfully. Recommend adopting it.

**Q3 — `unresolved_ids`.** Citations a claim made that do **not** resolve to a
collected row — i.e. a fabricated reference. A guard binds every claim back to
real rows and blocks the whole report if any fail, so this is normally empty and
a non-empty value is alarming rather than routine. It is recorded rather than
dropped because a silent drop is indistinguishable from the model finding
nothing. Label: **"citations that don't resolve to a collected row"**, and it
should be rendered as a warning, not a statistic.

**Q4 — `engagement` keys.** Free-shape by design; `{upvotes, replies}` is what
the current collectors emit and nothing enforces it. The plan's treatment —
render what is present, "not reported" when absent, never zero — is correct and
should stay key-agnostic rather than hard-coding two.

**Q5 — `intent_score`, `action`, `distribution_mode`.** Confirmed: nothing
outside the mining layer reads any of them. Cutting all three from the interface
is safe. They stay in the JSON export.
