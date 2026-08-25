# What the social-intelligence market actually sells

**Data collected 2026-08-25.** Every claim below carries its source. Where a
company's own marketing is the only source, it is labelled as such — these are
vendor claims, not measured facts.

The question this answers: *what separates these companies from naive keyword
scraping, and how do they package the result for a client?*

---

## 1. The short answer

Nobody sells collection. Collection is a line item — Bright Data, SocialGist,
an API. What they sell is a **transformation ladder**, and the rung they can
credibly claim is their price.

The industry's own summary of itself, from a 2025 comparative analysis of nine
platforms: *"Platforms are distinguished not by data volume but by how they
transform raw signals into actionable narrative and strategic foresight."*
([Britopian, 2025](https://www.britopian.com/social/social-intelligence-platforms-2025/))

Here is the ladder, assembled from what each company actually claims to do.

| Rung | Layer | Who does this, visibly | Vi's position today |
|---|---|---|---|
| 0 | **Keyword mention counting** | Table stakes. Nobody differentiates here. | Have it |
| 1 | **Corpus construction** — knowing *where* to look before you spend | Rarely stated publicly; it's the unglamorous half | **Have it** — the gold list |
| 2 | **Entity resolution against a domain ontology** — "Symproic", "naldemedine" and "that OIC drug" are one node | Tastewise: *"years of encoding food taxonomies, signals, and behaviors"* into a purpose-built **data graph, refreshed daily** | Partial — lexicon, no graph |
| 3 | **Author resolution** — *who* said it | CREATION.co: **3M+ human-verified HCP profiles** | **Latent — see §4** |
| 4 | **Multi-source corroboration** | Tastewise: **three independent sources must align** for a high-confidence finding. Spate: a trend on *both* TikTok and Google beats one on either | Not built |
| 5 | **Clustering + network structure** — topics → themes → drivers | NetBase Quid: network graphs, auto-named clusters. Black Swan: **200–400 trend clusters per category/market**, laddering up into "Growth Drivers" | Not built |
| 6 | **Momentum and forecast** — not what is said, what is *growing* | Black Swan TPV: 89% claimed accuracy, re-checked monthly. Spate: 72% at 12 months | Not built |
| 7 | **Anomaly surfacing** — what changed that nobody asked about | Ipsos Synthesio "AI Signals": surfaces trends **and anomalies** | Not built |
| 8 | **Finished artifact, not a dashboard** | Tastewise: *"done, not described"* — sell-in stories, innovation briefs, operator-ready narratives | Parent engine does this for content |
| 9 | **Published, backtested accuracy** | Black Swan re-checks predictions monthly. Spate **publishes its keyword list** and invites users to flag miscategorisations | Not built |

Rungs 0–1 are cost control. **Rungs 2–4 are the moat.** Rungs 5–7 are the
product. Rungs 8–9 are why a client renews.

---

## 2. What each company actually does

### Tastewise — the ontology-plus-corroboration model
*Food & beverage. The most transferable architecture found.*

- **Sources:** social conversations, restaurant menus, retail signals, consumer
  reviews, consumer panels, market trackers
- **Transformation:** raw data is *"decoded into demand signals, validated across
  independent sources, and continuously governed as consumer behavior changes"*
- **The rule worth stealing:** three independent sources must align for a
  high-confidence finding. Then a confidence score, then a **human evaluation
  layer**, before anything reaches a client
- **The substrate:** a purpose-built food & beverage **data graph**, refreshed
  daily, grounded in consumer, menu and retail signals
- **Delivery:** ten named agents, each mapped to a job — Trends, Marketing,
  Sales, Menu Innovator, Product Innovation, Concept Testing, New Product Launch
  Tracker, AI Survey, AI Recipe, plus TasteGPT as the conversational front
- **The positioning line:** outputs are *"done, not described"*, and *"traceable,
  explainable, and built to stand up in the room"*

Sources: [platform](https://tastewise.io/agentic-ai/platform) ·
[how it works](https://tastewise.io/blog/tastewise-ai-food-trend-analysis)

> **"Built to stand up in the room"** is the whole value proposition in five
> words. The buyer is a brand manager who has to defend a decision to their
> boss. They are not buying data; they are buying the ability to survive the
> meeting.

### Black Swan Data (Trendscope) — the forecasting model

- **Sources:** billions of consumer dialogues — Twitter, Reddit, blogs, forums,
  review sites, news & lifestyle publications
- **Transformation:** proprietary NLP strips noise, then every topic is
  structured into a trend framework. **Network analysis** works out how topics
  interrelate and *"ladder-up into Growth Drivers"*
- **The scoring layer:** a **Trend Prediction Value (TPV)** algorithm forecasts
  future growth. Trendscope 3.0 dynamically clusters into **200–400 higher-level
  Trend Clusters per category and market**
- **The trust mechanism:** *"experts go back and check their predictions every
  month to ensure they match real results"* — 89% claimed accuracy

Sources: [Trendscope](https://www.blackswan.com/trendscope/) ·
[Trendscope 3.0](https://www.blackswan.com/trendscope-3-0-introducing-dynamic-trend-clustering/)

### Spate — the cross-platform corroboration model

- **Sources:** trillions of signals from Google Search, TikTok, Reddit,
  Instagram. Explicitly *not* analyst opinion or survey panels
- **The core idea, stated plainly:** *TikTok captures what consumers aspire to,
  Google captures what they actually pursue.* A trend on both is a stronger
  signal than a trend on either. Momentum on TikTok that shows up in Google
  search and **holds over time** is the buy signal
- **Prediction:** 12 months forward at 72% claimed accuracy
- **Hygiene:** re-scrapes monthly for new keywords; **publishes its keyword list
  to users and invites them to flag miscategorisations**

Sources: [data FAQ](https://help.spate.nyc/en/article/spate-data-faq) ·
[forecasting method](https://www.spate.nyc/blog/beauty-trend-forecasting-how-to-identify-a-trend-before-it-peaks)

> Spate's aspiration-versus-pursuit split is a genuinely good idea and it has a
> direct healthcare analogue. **What an HCP posts in a public forum is
> professional positioning; what they search for is what they do not know.**
> Same asymmetry, higher stakes.

### The generalist platforms — what each one's single differentiator is

From the nine-platform comparative analysis
([Britopian, 2025](https://www.britopian.com/social/social-intelligence-platforms-2025/)):

| Platform | The one thing | Notable |
|---|---|---|
| **Talkwalker** (Hootsuite) | 187 languages, ~90% sentiment accuracy | Visual recognition finds "dark" mentions — logos with no text |
| **Brandwatch** (Cision) | Extremely flexible query language; "Iris" auto-discovers insights | **Sentiment only 60–70% out of the box** — needs human calibration |
| **NetBase Quid** | Network visualisation + AI text mining, custom taxonomies | Interactive cluster maps as the deliverable format |
| **Pulsar** | Audience Intelligence — segments *communities*, not keywords | Topic wheels expose sub-communities |
| **Ipsos Synthesio** | "AI Signals" surfaces trends **and anomalies** | Fuses social with Ipsos survey panels |
| **Digimind / Onclusive** | 15 emotion categories, 900+ chart types | "AI Sentinel" — predictive monitoring |
| **Meltwater** | Cross-media: social + news + influencers, 480 sources | 360° reputation reports |
| **YouScan** | Image recognition — logos, objects, scenes, demographics | Claims **up to 85% more brand mentions** from visuals alone |

Brandwatch's 60–70% out-of-box sentiment accuracy is the most useful number
here. The category leader by query flexibility has sentiment barely better than
a coin-flip-plus, and it is sold at up to $180K/year. That is the size of the
gap between *having* a sentiment field and having a trustworthy one.

---

## 3. What it costs — and the arbitrage

| Vendor | Annual cost | Notes |
|---|---|---|
| **Talkwalker** | ~$6K standard → $15K+ enterprise; custom from ~$9K | Now part of Hootsuite (acquired April 2024) |
| **Brandwatch** | ~$9.6K–$180K ($800–$15K/mo) | Vendr floor **~$20K/yr** — below that it is unreachable. Invoiced annually in advance, **non-cancellable, non-refundable** |
| **Sprinklr** | **$60K+ → $150K+** | **Discontinuing self-serve entirely on 2026-04-30**, going enterprise-only |

Sources: [Vendr — Brandwatch](https://www.vendr.com/marketplace/brandwatch) ·
[pricing comparison](https://www.xpoz.ai/blog/comparisons/social-listening-tools-pricing-compared-2026/) ·
[enterprise buyer's guide](https://www.pulsarplatform.com/guides/best-social-listening-tools-2026-guide-for-enterprise-buyers)

**Against that: a real Stage-2 sweep in the parent engine cost $0.0315, and a
full campaign runs ~$0.03 mining plus ~$1 of model.** A SERP request is $0.0015;
an Unlocker page fetch is $0.03.

Two things follow.

1. **The arbitrage is three to five orders of magnitude, and it is real** —
   because the cost is per-question, not per-seat-per-year. The comparison is
   not "our tool is cheaper than Brandwatch." It is that a $20K floor forces a
   client to ration questions, and cents-per-run does not. **The product is
   permission to ask a stupid question.**
2. **Sprinklr abandoning self-serve on 2026-04-30 vacates the exact position
   this tool occupies.** Enterprise-only is now the whole top of the market.

---

## 4. The pharma lane — and the thing Vi is sitting on

Brandwatch and Sprinklr are not the competition. These are.

### CREATION.co — the closest structural analogue to Vi

- **CREATION Pinpoint®**: an AI-powered global database of **3M+ human-verified
  HCP online profiles**, tracking billions of HCP conversations across public
  *and private* networks
- **The number that justifies the whole company:** *"typically only 2–5% of
  conversation on a disease area is made by healthcare professionals, and
  standard social listening tools are unable to filter the data in a way that
  will quickly separate HCP conversations from everything else, as they rely on
  keywords which can be unreliable and time-consuming"*
- **Influence, structurally measured:** assesses peer-to-peer influence — *who
  drives others to post, who is central to the conversation, who gains reach
  specifically among HCP peers.* This is network centrality, not follower count
- Runs a pharmacovigilance practice on top of the same corpus

Sources: [CREATION.co](https://creation.co/) ·
[why another tool](https://creation.co/knowledge/if-you-already-have-a-healthcare-social-listening-tool-why-implement-another-one/) ·
[PV webinar](https://creation.co/webinar/pharmacovigilance-in-hcp-social-media-listening/)

> **This is the finding that matters most.** If 95–98% of disease-area
> conversation is *not* from clinicians, then any sentiment number computed over
> unfiltered disease conversation is a patient sentiment number wearing a
> clinical label. Author resolution is not a refinement on top of listening — it
> is the precondition for the output meaning anything at all.
>
> And Vi already owns the harder half of it. CREATION has 3M verified HCP social
> profiles. Vi has **7.24M HCPs in Provider360**, an **NPI↔HEM bridge**, and a
> 375.7M-row consumer identity graph. CREATION built an identity layer to make
> social data mean something. Vi has an identity layer and has not yet pointed
> it at social data.
>
> The unresolved question is the join: social handle → NPI. That is one hard
> problem, not a platform. It is worth scoping on its own.

### IQVIA — Social Media Intelligence for Pharma

Sells: digital trend discovery, brand reputation, **social patient journey
mapping**, unmet-need identification, and **DKOL (Digital Key Opinion Leader)
identification and profiling**. Positions on life-sciences expertise and
compliance methodology rather than on tooling. Deliverables are launch
monitoring, patient research, and enterprise KPI dashboards.
([IQVIA](https://www.iqvia.com/solutions/commercialization/commercial-analytics/primary-intelligence/social-media-intelligence-for-pharma-and-consumer-health))

### Talking Medicines — Drug-GPT / PatientMetRx®

Domain-specific LLMs over patient and HCP conversation. The differentiator worth
copying: a **dual-lens comparison** that assesses *how well messaging speaks to
patients versus HCPs, before and after launch* — the two lenses run over the
same corpus and **the gap between them is the product**. Claims an 80%
productivity uplift over manual insight extraction.
([Talking Medicines](https://talkingmedicines.com/use_cases/mastering-hcp-engagement-with-tailored-messaging-through-drug-gpt-intelligence/))

### Real Chemistry

NLP over HCP publications and social activity to infer research interests and
areas of expertise; positions as *"a blend of healthcare expertise, human
ingenuity, and advanced AI."*
([Real Chemistry](https://www.realchemistry.com/real-ai-at-real-chemistry/))

---

## 5. Vetric is not what we thought

Vetric now positions as **video-first threat detection and brand protection** —
*"the intelligence backbone for a safer world."* 10B monthly signals, monitoring
for **impersonations, counterfeits and brand abuse**, sold to public safety and
corporate security. They claim 70% of the world's public safety leaders and 200+
partners. No API/pricing published. ([vetric.io](https://vetric.io))

That is a different category from consumer listening. If Vetric is on Vi's
radar as a social-data source for insight work, the premise needs re-checking —
they are selling brand-abuse and threat intelligence now.

---

## 6. The regulatory finding — this is a design constraint, not a footnote

**EMA Good Pharmacovigilance Practices, Module VI (Rev 2):** marketing
authorisation holders must **regularly screen digital media under their
management or responsibility** for potential reports of suspected adverse
reactions. "Digital media" explicitly includes websites, blogs, vlogs, social
networks, internet forums, chat rooms and health portals.

Neither FDA nor EMA mandates social listening as a standalone activity. But the
rule that matters is: **if you find an adverse event online, you are responsible
for reporting it, exactly as from any other source.**

And the sentence that turns this from a risk into a moat: GVP Module VI accepts
digital and publicly accessible sources as valid inputs **"as long as social
listening and monitoring methods are systematic, well-documented, and
verifiable."**

Sources: [Resolver — PV social signal detection](https://www.resolver.com/blog/pharmacovigilance-social-signal-detection/) ·
[Datashake — AE monitoring](https://www.datashake.com/blog/adverse-event-monitoring-on-social-media-what-pharma-teams-need-to-know) ·
[ProPharma](https://www.propharmagroup.com/thought-leadership/the-importance-of-social-media-monitoring-in-pharma) ·
[compliance guide](https://ehealthcaresolutions.com/can-pharma-finally-use-social-media-social-listening-compliance/)

Two consequences, and they point in opposite directions.

**The obligation.** A tool that surfaces public posts about a client's product
will eventually surface a suspected adverse reaction. Surfacing it to the client
starts their clock. The tool therefore needs a **safety-signal flag and a
defined route** — not because the tool reports anything (it must not), but
because an unflagged AE sitting in a themes table is worse than one that was
never collected.

**The moat.** *"Systematic, well-documented, and verifiable"* is a near-verbatim
description of what the parent engine already produces: a per-row ledger with
URL, venue, capture timestamp, collection method, cost, and an explicit
keep-or-drop reason for every candidate — plus a coverage artifact recording
which venues answered and which came back empty. Brandwatch's 60–70% sentiment
and an opaque black-box query do not clear that bar. **Vi's provenance discipline
is not overhead being carried from the parent; it is the feature that makes the
output admissible in a regulated conversation.**

---

## 7. So what — six recommendations

1. **Sell the rung, not the scrape.** Rungs 0–1 are already commodity. Vi's
   defensible claim is rungs 2–4: a health ontology, author resolution, and
   multi-source corroboration. Everything below rung 4 is a feature; rung 3 is a
   business.

2. **Adopt the three-source rule and confidence scoring as a hard gate**, the way
   Tastewise does. A finding corroborated once is an anecdote; the artifact
   should say which tier every finding sits in and refuse to promote an
   uncorroborated one. This is the same discipline as the parent's
   claim-must-bind-to-a-source rule, applied one level up.

3. **Split every metric by venue class and never blend.** A sentiment number
   spanning a guideline body and a patient forum describes nothing that exists —
   and given the 2–5% figure, an unsplit disease-area sentiment score is a
   patient number mislabelled as clinical.

4. **Build the dual-lens gap as a first-class output.** HCP view versus patient
   view of the same product, and the delta between them. Talking Medicines sells
   this; it is cheap to compute once author class is known; and it is the
   clearest instance of the thing the brief asked for — *something the client
   did not know to ask for.*

5. **Scope the social-handle → NPI join as its own piece of work.** It is the
   highest-value and highest-difficulty item found in this research, it is where
   Vi's existing assets create an advantage nobody else can copy, and it must
   not be smuggled into a UI project.

6. **Flag suspected adverse events; never report them.** Detect, label, route to
   a named human, record that it was routed. The parent's rule — *the engine
   never posts* — generalises exactly: **the engine never files.**

---

## 8. Open questions for a human

- **R1** Does surfacing a suspected AE to a Vi client, from public data Vi
  collected, place any duty on **Vi**, or only on the marketing authorisation
  holder? This is a legal question, not a product one, and it gates any client
  delivery. Related to the parent engine's open item O3.
- **R2** Is a social-handle → NPI join permitted under the licences covering
  Provider360 and the Pipl NPI↔HEM bridge? The technique is worthless if the
  licence forbids the join.
- **R3** Do the accuracy claims quoted here (Black Swan 89%, Spate 72%,
  Talkwalker ~90% sentiment) have any published methodology behind them, or are
  they marketing? Vi should not quote a competitor's number it has not seen
  substantiated, and should expect the same scrutiny of its own.
