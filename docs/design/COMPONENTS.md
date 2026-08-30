# Components

The shared layer: every macro, filter and route variable a screen may use.

You are editing **one template**. Everything you need already exists here — if
a component you want is not on this page, it does not exist, and the right move
is to compose the ones that do rather than to invent markup. The stylesheet,
the macros and the route context are owned by one agent and are frozen from
your side.

Three things hold everywhere and are not negotiable:

1. **No JavaScript.** `<details>`, the native `popover` attribute, `:target`
   and query-string links are the whole interaction budget.
2. **StrictUndefined.** Every variable a template touches must be defined on
   every path. The helpers below return the *same keys on every path* so you
   never need a guard; the route context tables say which variables exist.
3. **It must print.** A figure that is only legible on screen is not finished.

---

## 1. How to think about a screen

Every screen has three layers, and must separate them on **at least three** of
six axes at once — size, weight, colour, position, enclosure, density.

| Layer | Holds | Visible on arrival? | Built with |
|---|---|---|---|
| **1 — Answer** | The figure and the one clause naming what it is | Yes, largest type on the screen | `stat(size="xl")`, `.fig-xl`, `card-lead` |
| **2 — Support** | The comparison, the count, the direction, the confidence | Yes, at meta weight beside or beneath layer 1 | `delta()`, `sources()`, `.t-support`, `.t-meta` |
| **3 — Depth** | Method, caveats, definitions, the rows, the rationale, the full prose | **Behind a control** | `read_more()`, `info()`, `.layer-depth` |

Nothing is deleted to reach layer 3. It moves.

**The weight axis is thinner than you expect.** `vsm/ui/static/fonts/` ships
Neue Montreal Book (400) and Medium (500) and nothing else. 500 is the heaviest
emphasis that exists; anything above it is a browser-synthesised faux-bold that
misrepresents the pinned typeface. Never write `font-weight: 600` or `700`. The
other five axes have to carry the difference.

**Violet is one action per screen.** `--signal` marks the single primary button
and nothing else. Data marks are ink (`--fg1`). One deliberately-highlighted row
may take it (`bar_row.emphasis`), and that is the entire allowance.

**A null is a word, a zero is a numeral, and neither is a dash.** `—` is
reserved for "this field does not apply to this row type". Every helper below
already obeys this; do not undo it in a template.

---

## 2. Figure macros

Import from `_macros.html`. Each is self-contained: it emits its own
`<figure>`, its own `<figcaption>` stating the figure's key value, and its own
empty state. **Do not wrap them in another `<figure>`.**

Each takes the output of a geometry helper (§3), never raw artifact JSON.

### `bar_list(rows, summary="", unit="mentions", data_label="", empty_note="")`

A ranked horizontal bar list — the shape for 3–15 named categories. Sorted
descending, label left, count printed at the bar end.

* `rows` — output of `bar_rows(...)`.
* `summary` — the caption. State the figure's key value; **never** explain how
  to read the chart. Omit it and the macro writes a bland fallback, which is
  worse than a real one.
* `empty_note` — the named empty state for *this* region, when `rows` is empty.
  Always pass it. "Nothing counted here yet" is the fallback and it claims
  nothing about the cause, which is the only reason it is allowed to exist.

```jinja
{{ bar_list(theme_bars,
            summary="Cost of access leads with 14 mentions of 41.",
            data_label="Themes by volume",
            empty_note="Nothing collected yet — this topic has never been swept.") }}
```

Never a pie or a donut for this shape. Never a word cloud, including for
entities and brand names — entities render as a ranked bar list.

### `bullet(label, value, prior=none, prior_label="", scale=none, unit="")`

Level and change in one row: a solid bar for now, a tick where it stood last
sweep.

* `prior=none` draws no tick and the value line reads **"first sweep"** in
  words. Never a dash, never `0%`, never `+100%`.
* `scale` — the value the full width represents. **Pass the largest value in
  view** whenever you render a column of bullets, or each one silently gets its
  own scale and the column stops being comparable.

```jinja
{% for m in momentum_bullets %}
  {{ bullet(m.name, m.now, m.prior, "12 Aug", scale=m.scale, unit="mentions") }}
{% endfor %}
```

### `sparkline(series, label="", title="")`

Volume across sweeps, spaced by the dates the sweeps actually happened on, so a
missed week reads as a gap.

`series.shape` decides what is drawn and you do not override it:

| `shape` | Sweeps | Drawn as |
|---|---|---|
| `empty` | 0 | a short "no sweep yet", not a blank frame |
| `dot` | 1 | one dot carrying its value — one point is not a trend |
| `pair` | 2 | two dots against a rule, never a connecting slope |
| `dots` | 3 | three dots, still no line |
| `line` | 4+ | a polyline with every dot visible |

The 4-point floor is charts.csv row 1's ("fewer than 4 data points → use a stat
card"). It is stricter than UX-PLAN §4's "≥3 = polyline"; the rulebook wins,
and `series_points(..., polyline_min=3)` is available if a screen has a reason
to disagree in writing.

```jinja
{{ sparkline(row.volume_series) }}
```

### `dumbbell(chart, level=3, heading="Clinicians vs patients")`

The clinician-versus-patient gap on one shared −1…+1 axis. The connector's
length *is* the gap.

Renders two blocks: the comparison, then — separately, under its own heading —
**"Discussed by one audience only (n)"**. That separation is a correctness
requirement, not a layout preference: a theme one audience never raised has no
gap, and averaging it into the comparison would say the silence was agreement.
The macro handles both; you pass the whole chart.

* `level` — the heading level for the one-audience group. Keep the page outline
  sequential; if your surrounding section is `<h2>`, pass `3`.

```jinja
{{ dumbbell(gap, 3) }}
```

Never a radar chart for this. Never a grouped bar with a shared colour key and
no printed values.

### `sentiment_bar(fid, mix, label="")`

The five-way mix as a 100% stacked bar, fixed segment order — Positive, Mixed,
Neutral, Negative, Couldn't tell — with `n` printed adjacent. "Couldn't tell" is
unfilled and always last so it never reads as an opinion.

* **`fid` must be unique on the page.** It namespaces the SVG `<pattern>` ids,
  which are document-global; two mixes sharing an `fid` paint one of them with
  the other's texture. Use the theme id.
* Below **n = 5** no bar is drawn at all — the macro prints the raw counts and
  says why. Below **n = 20** the bar is drawn but labelled in counts, not
  percentages.

```jinja
{{ sentiment_bar("theme-" ~ row.theme.theme_id, row.mix, row.name) }}
```

### `coverage_strip(fid, grid, level=3)`

One cell per site, four nominal states: solid (returned rows), hairline outline
(returned nothing), hatched (blocked us), dashed outline (not tried). Below the
strip: a legend with counts, the **named** lists for the three non-happy states,
and a per-site data table inside a `read_more`.

Not a colour ramp. "Blocked us" is not more of anything than "returned
nothing", and a ramp would imply an order that does not exist.

* `fid` — page-unique, as above.

```jinja
{{ coverage_strip("cov", coverage_view) }}
```

### `spend_meter(m, label="Spend against the cap")`

Fill is spent, tick is the estimate, hard rule is the cap; all three printed
beside the bar. "Stopped at the cap" renders as a terminal stop bar — a shape,
not a status word, so a successful partial does not read as a failure.

One metric per meter. Do not stack two.

```jinja
{{ spend_meter(spend) }}
```

### `pair_bars(before, after, before_label, after_label, absent_note="")`

An anomaly's before and after, side by side. When `before` is `none` — a theme
that did not exist last sweep — the prior slot is an outlined empty frame
carrying `absent_note` in words. **Never a bar of height zero**: a zero-height
bar and "this did not exist yet" look identical and mean different things.

```jinja
{{ pair_bars(a.baseline, a.observed, "12 Aug", "19 Aug", a.absent_note) }}
```

---

## 3. Geometry helpers

Registered as Jinja globals, so callable from any template. Most routes already
call them for you (§5) — use the route variable when there is one, because the
route's copy is the same object the client report draws from and the two must
not diverge.

Every one returns a **uniform key set on every path**. There is no `none` to
guard against and no key that only appears when the data is unusual.

### `bar_rows(rows, sort=True, limit=None, unit="mentions") -> list[dict]`

Accepts mappings (`label`, `value`, and optionally `href`, `note`, `emphasis`)
or `(label, value)` pairs. Each returned row:

`label` · `value` · `value_label` (thousands-separated) · `pct` (share of the
largest row — the bar's length) · `share_pct` (share of the total) · `href` ·
`note` · `emphasis` · `rank` · `unit`

`sort=False` preserves input order — use it when the reading order is fixed
(cheapest sweep size first, stages in the order they run).

### `series_points(points, width=150, height=38, pad=6, polyline_min=4, unit="mentions") -> dict`

`points` are mappings with `date` (ISO) and `value`, optionally `href`.

`shape` · `count` · `width` · `height` · `pad` · `baseline_y` · `points[]`
(each `x` `y` `value` `value_label` `date` `date_label` `date_long` `href`
`is_last` `index`) · `polyline` (empty unless `shape == "line"`) · `lo` · `hi` ·
`lo_label` · `hi_label` · `first_label` · `last_label` · `latest` · `spacing`
(`date` | `even` | `index`) · `unit` · `summary`

### `gap_chart(rows, domain=1.0) -> dict`

`rows` are mappings with `name`, `hcp_net`, `patient_net`, and optionally
`divergence`, `volume`, `independent_sources`, `reason`, `tier`. When
`divergence` is absent it is computed as patient minus clinician.

`rows[]` (comparable only, widest gap first) · `single[]` (one audience only) ·
`widest` · `count_comparable` · `count_single` · `total` · `domain` ·
`axis_low` · `axis_mid` · `axis_high` · `summary`

Each row: `name` `volume` `volume_label` `sources` `hcp` `patient` `hcp_label`
`patient_label` `hcp_pct` `patient_pct` `gap` `gap_label` `comparable`
`present` (`both`|`clinicians`|`patients`|`neither`) `missing_label` `reason`
`left_pct` `width_pct` `dot_pct` `tier` `summary`

### `sentiment_mix(counts, min_n=5, percent_min_n=20) -> dict`

`counts` maps the internal stance keys (`positive` `mixed` `neutral` `negative`
`unclear`) to integers. Anything missing is a zero — the one place in this
codebase where zero is the honest reading, because it means nobody said it.

`segments[]` (`key` `label` `count` `count_label` `pct` `pct_label`
`value_label` `unfilled`) · `n` · `n_label` · `proportional` · `show_pct` ·
`min_n` · `too_few_note` · `summary`

### `coverage_grid(coverage, known=None) -> dict`

`coverage` is `coverage.json` (or `None`). `known` is an optional full site
registry; without it, "not tried" is empty because nothing knows what was not
attempted.

`cells[]` (`site` `state` `state_label`) · `states[]` (`key` `label` `count`
`sites` `named` `named_count`) · `counts` · `labels` · `total` · `has_data` ·
`summary`

### `meter(spent, estimate=None, cap=None, stopped=False, decimals=2) -> dict`

`spent` `estimate` `cap` · `spent_label` `estimate_label` `cap_label` ·
`spent_pct` `estimate_pct` `cap_pct` · `has_estimate` `has_cap` · `stopped`
`over` · `state` (`within`|`over`|`stopped`) · `summary`

---

## 4. Chrome and layering macros

### `read_more(summary, open=false)` — a `{% call %}` macro

Layer 3. Renders the body **twice**: once inside a `<details>` for screen, once
inside a `.print-only` block that only appears in print. That second copy is
the fix for a real limitation — a closed `<details>` does not render its
content slot, so no CSS and no server-side markup can force it open at print
time, and there is no script here to do it either.

**Because the body is emitted twice it must not contain an `id`, a form
control, or an anchor target.** Two elements would share one id. Put those in
the always-visible layer.

`open` is the default state and can only be set server-side. Open it when the
reader is already looking for the detail (a guard that blocked something, an
error explanation); leave it closed for background.

```jinja
{% call read_more("How this was counted") %}
  <p>One forum post is one source. One publisher is one source however many
  pages it runs.</p>
{% endcall %}
```

### `card(title, level=2, tip="", id="")` — a `{% call %}` macro

A titled section bounded by a hairline. `level` keeps the outline sequential.
`tip` is a `DEFINITIONS` key (§6) rendered as the `(i)` beside the title.

```jinja
{% call card("What moved", 2, tip="change") %}
  {{ bar_list(moved_bars, summary=…) }}
{% endcall %}
```

### `stat(label, value, sub="", tip="", size="")`

One scorecard cell. `size` is `""`, `"sm"`, or `"xl"`. **One `xl` per screen** —
a second is two screens fighting. Put several in a `<div class="scorecard">`.

### `empty(fact, cause="", href="", action="")`

A named empty state. Template: *[Fact]. [Cause if known]. → [one link].*

At least five different truths produce an empty region on this product —
"first sweep", "nothing moved", "collected but not analysed", "never
collected", "filtered to nothing". A shared "No data" collapses all five and is
a defect. Name yours.

### `chip(label, href, on=false, note="", removes="")`

A filter chip as a native `<a>` with its state in the text. `note` renders as
**visible caption text** — never use a `title` attribute for this: a native
tooltip is unreachable by keyboard, invisible on touch and absent in print.
`removes` names what following the link takes away ("Clear site").

### `sort_th(label, key, sort, base, numeric=false)`

A sortable column header carrying `aria-sort`, set server-side from the query
string. `base` is the route's `sort_base` variable, which already holds every
other parameter and ends in `sort=`.

```jinja
<thead><tr>
  {{ sort_th("Site", "venue", sort, sort_base) }}
  {{ sort_th("Captured", "captured", sort, sort_base) }}
</tr></thead>
```

### `stamp(value, long=false)`

`<time datetime="…">` with a readable label. Use this for **every** timestamp.
`long=true` gives `25 August 2026` — use it anywhere that can reach paper;
short dates like "19 Aug" are ambiguous on a printed page opened in February.

### `error_summary(errors, labels={}, anchors={}, heading=…)`

The focusable `role="alert"` summary at the top of a form, one linked item per
invalid field. Keep the inline per-field errors as well — this is in addition
to them, not instead. The form routes pass `field_labels` and `field_anchors`.

```jinja
{{ error_summary(errors, field_labels, field_anchors) }}
```

### `mark(direction)`

An inline SVG glyph: `"up"`, `"down"`, `"flat"`. Use this rather than `▲`,
`▼` or `–`: Neue Montreal almost certainly carries none of those, so a typed
one falls back to a different typeface per glyph and shifts between machines
and in print. No icon font can be loaded in this app.

### Already existing, unchanged

`page_header(title, meta=[], tip="")` · `flow_rail(topic, flow, current)` ·
`tier_badge(tier, linked=True)` · `ref_marks(refs)` · `sources(n)` ·
`delta(pct, baseline_label)` · `info(term)` · `table_scroll_open(label)` ·
`title_block(items)` · `deliverable_tiers` · `deliverable_downloads` ·
`deliverable_promise`

Two notes on those:

* `delta()` now draws its own direction glyph. Nothing to change at call sites.
* `deliverable_downloads()` **needs no lede**. `run.html`, `snapshot.html`,
  `insight.html` and `report.html` each carried a hand-written sentence saying
  "some of these are ready and some are not" — a fact the list itself shows,
  because every pending row is labelled "Not run yet". Delete yours.

---

## 5. Route context

Everything below is defined on every render of that route. Anything not listed
does not exist — asking for it is a 500 under StrictUndefined.

Variables marked **new** were added for this rebuild.

### `/` — overview.html
`counters` `moved` `moved_total` `moved_comparable` `moved_threshold`
`divergence` `divergence_total` `not_comparable` `sayable` `sayable_total`
`emerging` `attention` `attention_total` `analysed_topics` `synthetic`
`active_nav`
**new:** `moved_bars` (bar_rows) · `moved_bullets` (each `name` `topic` `now`
`prior` `delta_pct` `href` `scale`) · `gap` (gap_chart) · `sayable_bars`

### `/topics` — topics.html
`rows` `first_run_steps` `sorts` `filters` `filter_help` `filter_lede` `q`
`sort` `show` `total` `shown` `matched` `capped` `row_cap` `uncapped`
`active_nav`
**new:** `sort_base` (for `sort_th`) · `filter_chips` (each `key` `label`
`note` `on` `href` — for `chip()`, replacing the `title` attribute)

Each `rows[]` entry: `topic` `snapshot_count` `last_snapshot_run_id`
`last_snapshot_at` `spend_to_date` `latest_volume` `sparkline` (superseded)
**new:** `volume_series` (for `sparkline()`)

### `/topics/{id}` — topic_detail.html
`topic` `history` `has_run` `tiers` `latest_mine` `latest_insight`
`latest_report`
**new:** `volume_series` · `spend_series` · `sweep_rail` (each `run_id`
`started_at` `short` `long` `href` `is_current`) · `spend_to_date`

### `/topics/new`, `/topics/{id}/edit` (and the 422 re-render) — topic_form.html
`mode` `topic` `band_cards` `errors` `values` `field_guide`
**new:** `field_labels` · `field_anchors` (both for `error_summary`)

### `/topics/{id}/confirm` — confirm.html
`topic` `band` `estimate` `cap_usd` `changes_band` `tiers`
**new:** `size_bars` (the three sweep sizes on one scale, cheapest first,
`emphasis` on the chosen one) · `chosen_band`

### `/topics/{id}/delete` — topic_delete.html
`topic` `counts` `spend` `warning`

### `/runs/{id}` — run.html
`run` `topic` `stages` `cost_detail` `next_snapshot_run_id`
`next_insight_run_id` `flow` `current_step` `deliv_tiers` `synthetic`
**new:** `spend` (meter, always a full dict even where `cost.json` is gone) ·
`stage_bars` · `stages_done`

### `/runs/{id}/snapshot` — snapshot.html
`run` `topic` `rows` `total_rows` `coverage` `mix` `filters` `options`
`any_filter_active` `flow` `deliv_tiers` `synthetic`
**new:** `mix_bars` · `coverage_view` (coverage_grid — always a dict; when
`has_data` is false the strip renders its own empty state) · `spend` ·
`volume_series` · `spend_series` · `sweep_rail` · `sort` · `sort_base` ·
`active_filters` (each `key` `label` `value` `clear_href`) · `matched_rows` ·
`capped` · `uncapped` · `row_cap` · `all_href`

Query parameters: `venue` `kind` `tier` `date` `sort` (`captured`|`venue`|
`kind`|`theme`) `all=1`.

### `/runs/{id}/insight` — insight.html
`run` `topic` `mine_run_id` `snapshot_rail` `plot_guide` `forest_svg`
`forest_rows` `momentum_rows` `has_baseline` `anomaly_rows` `theme_rows`
`stance_rows` `entity_rows` `unmapped_count` `flow` `deliv_tiers` `synthetic`
**new:** `gap` (gap_chart) · `theme_bars` · `entity_bars` · `momentum_bullets`
(each `name` `now` `prior` `delta` `delta_pct` `reason` `scale`) ·
`anomaly_pairs` (each `name` `kind` `kind_label` `observed` `baseline` `detail`
`note` `absent_note`) · `sentiment_rows` (each `name` `basis` `mix`,
`by_class[]` of `cls` `label` `mix`) · `volume_series` · `spend_series` ·
`sweep_rail` · `view` · `views` (each `key` `label` `on` `href`)

Query parameter: `view` (`momentum`|`anomalies`|`themes`|`stance`|`entities`).
The five panels were CSS radio tabs, so nobody could send a colleague the
Anomalies view or reach it with the back button. Render them as links from
`views` and open on `view`; keep every panel in the response body so the
printed page and a CSS-off reader still get all five.

### `/runs/{id}/report` — report.html
`run` `topic` `pulse_href` `insight_run_id` `mine_run_id` `doc` `figure`
`theme_rows` `corroborated` `corroborated_note` `emerging` `emerging_note`
`lead_html` `extra_sections` `citations` `methodology_html` `considering_html`
`has_pulse` `flow` `deliv_tiers` `synthetic`
**new:** `gap` · `theme_bars`

`report.html` must contain **no `<details>` at all** — a test enforces it, and
it is what guarantees the client document prints whole regardless of engine. Do
not use `read_more()` there.

### `/how`, `/deliverables`, error page
`/how`: `what_it_is` `modes` `tiers` `glossary` `active_nav`.
`/deliverables`: `tiers` `example` `active_nav`.
Error page: `title` `message`.

---

## 6. Filters, globals and vocabulary

### Filters
`usd(decimals=4)` · `pct` · `sweep_size` · `net(lens)` · `net_short(lens)` ·
`dt` (now carries the zone) · `date_long` · **new** `date_short` · **new**
`iso` (the machine-readable original, for a `<time datetime>` attribute)

### Globals
`tier_label` `tier_note` `kind_label` `class_label` `stance_label`
`anomaly_label` `explainer` `definitions` **new** `define` `MODE_LABELS`
`tagline` `ephemeral_storage_notice` `read_only_control_note`
`storage_is_durable()` — plus the six geometry helpers of §3.

### Definition keys available to `info()` and `card(tip=…)`

`sources` · `3+ sources` · `gap` · `no comparison` · `sweep` · `tone` ·
`mention` · `access basis` · `sweep size` · `returned nothing` · **new**
`blocked us` · `not tried` · `coverage` · `cap` · `estimate` · `theme` ·
`anomaly` · `change` · `sentiment`

An unknown key renders **nothing** rather than raising, so a copy gap shows up
in review as a missing `(i)` instead of a 500 on a client-facing page. If you
need a term that is not here, say so — do not inline a definition in prose.

### Banned from anything a reader sees

`corroborated` (and `corroborate`) · `emerging` · `single_source` · `tier` ·
`band` · `dual-lens` (and `lenses`) · `NE` · `momentum` · `snapshot` (say
**sweep**) · `signal` (say **mention**) · `venue` (say **site**)

Ban the *root*, not the inflection a test happens to grep for.
`tests/test_ui_layers.py` enforces the literals; the rest is on you.

Replacements live in `vsm/modes/vocabulary.py` (`SWEEP_SIZE`, `MODE_LABEL`,
`SOURCE_LABEL`, `SOURCE_ADVICE`) and are reached through the filters and
globals above. Do not add a second spelling of anything.

---

## 7. Rules a review will check

* Every graphic carries its number as text, in the DOM, always.
* Every figure is a `<figure>` with a `<figcaption>` stating a **value**. A
  caption that explains how to read the chart means the chart is wrong.
* No figure relies on colour alone. Length, position, pattern, outline style or
  a printed number carries it too.
* An empty region is a **named** empty state, never a blank frame.
* Percentages only at n ≥ 20. Below that, raw counts.
* Every delta carries a sign and a **named baseline date**.
* One `<h1>` per page, no skipped heading levels. A `<summary>` is not a
  heading.
* Prose holds a 65–75ch measure. Figures and tables take the full column.
* Long statements and excerpts get a `read_more`, never a line clamp — a
  finding's statement is the product's output, and clamping it deletes the
  deliverable.
* Every wide table sits in `table_scroll_open(label)` (or its own
  `tabindex="0" role="region" aria-label`), and every table has a `<caption>`
  and `scope`d headers.
* Pointer targets are 24 CSS px (WCAG 2.2 AA), not 44pt.
* `autocomplete="off"` on every text input; `spellcheck="false"` on the search
  box. Nothing in this app is an address or a credential, and a password
  manager volunteering itself on a topic form is noise.
* Curly quotes and apostrophes, everywhere. This product prints.
* `autofocus` is conditional: the first errored control when there are errors,
  otherwise only on create. Never in edit mode, where it skips the `<h1>` that
  says which topic is being edited.

---

## 8. Known gaps, deliberately left

Not oversights — flagged so nobody re-litigates them silently.

* **`_base.html` is owned by nobody in this pass.** Three checklist items live
  there and are unfixed: `<meta name="theme-color" content="#FFFFFF">`, a
  `<link rel="preload">` for the two self-hosted TTFs, and the footer help
  link's position. Worth a follow-up ticket.
* **`vsm/modes/report.py` writes the generated markdown** and is outside this
  layer. Several writing-guidelines findings are against it: raw enum tokens
  (`hcp_discussion`, `theme_appeared`) reaching a client file, a 6-column
  header over a 5-column delimiter row, "up 0.0%" for a delta of zero, and an
  unconditional "worth considering" suggestion identical on every report.
* **`sparkline_svg()` in `render.py` is superseded** by `series_points()` +
  `sparkline()`. It spaces points evenly and draws a line through two of them.
  It stays only so `topics.html` keeps rendering until that screen is rebuilt;
  delete the `row.sparkline` call site and it can go.
* **The volume series is capped at 12 sweeps** on the snapshot and insight
  screens (`_SERIES_CAP` in `app.py`). Each point is one `signals.json` read,
  and this app has a documented history of a page hitting the 60-second
  serverless ceiling by fanning out reads one at a time. The watchlist is
  uncapped because it has already paid those reads for its own counts.
