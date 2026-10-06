# KAIROS System Design v0.3.1

**Current Design Baseline — 2026-10-07**

## 1. Purpose and boundary

KAIROS is a small local Python application that improves three-month investment decisions for one stock specified by the Human. v0.3.1 preserves the v0.2 Company analysis and the v0.3 prospective News design, while making ticker taxonomy entries optional enrichment rather than a mandatory ticker master.

KAIROS does not discover stocks, manage a portfolio, or use paid data. It produces a Markdown research report; the Human makes the final investment decision and performs any Broker operation.

Keep the system under 3,000 LOC where practical, with 10,000 LOC as a hard ceiling. Do not add a feature, abstraction, or module unless the current system needs it.

## 2. Baseline rationale and status

At `2026-06-30`, Step A produced `WATCH / MEDIUM` for 7203, 9984, and 6857 in all three runs. After Company Context, 7203 became `AVOID / MEDIUM` in all three runs, while 9984 and 6857 remained `WATCH / MEDIUM` in all three runs.

Company evidence improved differentiation, but broader Market, Sector, and News context may explain price behavior that Company data alone cannot. Success is not measured by producing more `BUY` recommendations.

The v0.3 RSS/raw-storage Step 1 and deterministic taxonomy-matching Step 2 are implemented baselines. Step 2 currently requires a ticker entry; v0.3.1 changes that maintenance model in the next small implementation step. News selection, three-call integration, and reporting remain future implementation work.

## 3. Fixed pipeline and modules

```text
Manual news-update (separate command)
  -> verified RSS metadata
  -> acquire only new/different items
  -> DATA_ROOT/news/raw/YYYY-MM-DD.jsonl

Human-specified ticker -> analyze
  -> J-Quants acquisition, as-of filtering, raw archive
  -> verified company identity + optional Human enrichment
  -> deterministic news matching and recency selection from stored records
  -> Call 1: Fundamental / Valuation / Bull
  -> Call 2: independent Bear / Risk
  -> Call 3: Contradiction / Thesis / Invalidator / Recommendation
  -> deterministic Allocation and Risk Check
  -> Markdown Investment Report -> Human decision
```

The production modules are exactly:

- `main.py`: argparse, `.env` / config, logging, `analyze`, `news-update`, orchestration
- `data.py`: J-Quants acquisition, as-of filtering, compact shaping, raw archive
- `news.py`: Human-editable news config loading/validation as needed, RSS retrieval/parsing, raw JSONL persistence, URL deduplication, deterministic keyword matching, selection
- `llm.py`: three model calls, prompts, JSON Schemas
- `risk.py`: `portfolio.json`, Allocation, Risk rules
- `report.py`: Markdown Investment Report

Do not split RSS, classifier, taxonomy, event, or crawler concerns into more production modules. Use the standard library by preference. A tiny RSS parser dependency may be proposed during implementation only if verified heterogeneous feeds demonstrate that it is simpler or safer; it is not pre-authorized.

## 4. Commands and collection operation

The established analysis interface remains:

```text
python main.py analyze 7203
python main.py analyze 7203 --as-of 2026-06-30
```

The separate `news-update` CLI/batch operation is manual/on-demand initially. An external Task Scheduler may invoke it later, but KAIROS contains no daemon or scheduler.

`analyze` never fetches RSS, news, or Web content. Stored news is reused across analyses. A news-update retrieves feed metadata only and writes only new or changed items.

Start with a few feeds whose actual endpoint and usage conditions have been verified. Candidates include official JPX, BOJ, FSA, FRB, and ECB feeds. Newspaper, investment-site, and Minkabu feeds require the same verification before use. RSS-list sites are discovery aids, not original sources.

## 5. J-Quants Company context and identity

Company quantitative data stays as designed and implemented in v0.2. `data.py` uses only needed J-Quants endpoints, archives responses under `DATA_ROOT` as research records rather than cache infrastructure, and constructs simple nested dictionaries. Missing or empty values are `null`, never invented values or zero.

With `--as-of`, only records available by `analysis_as_of` are usable; the actual latest source date used is `data_as_of`. Without it, use available latest data. The feature is a historical sanity check, not a Point-in-Time backtest or proof of performance.

For every analyzed ticker, obtain basic company identity from J-Quants listed-company/master data when available: ticker/code, Japanese company name, English company name only if actually provided, and official industry/classification only as actually supported. Implementation must verify the real raw/API field names and casing; this design does not invent them. Official industry remains separate from KAIROS Sector.

Japanese company names and any actually supplied English company names form baseline Company aliases. Latin matching is case-insensitive. Formal names may be poor headline aliases, so optional Human enrichment may add shorter aliases. Automatic identity matching can produce false positives; correct observed cases through enrichment instead of building a complex entity resolver.

Company Context remains compact:

- snapshot: price, revenue, operating profit, net profit, equity ratio, PER when available;
- comparable history: FY to prior FY and each cumulative quarter to the same prior-year period; never compare incompatible periods;
- metrics: revenue, OP, NP, operating/net margin, equity ratio, EPS, and only an appropriate latest full-year ROE;
- cash flow: operating CF, investing CF, financing CF, cash equivalents only when present, with NP comparisons only for compatible periods;
- forecast: latest relevant as-of-safe current-fiscal-year revenue, OP, NP, EPS, dividend; forward PER only from valid forecast EPS and as-of-safe price;
- price trend: adjusted-close returns over 21 / 63 / 126 / 252 trading observations, with insufficient history as `null`.

Optional context does not expand the established `REQUIRED_FIELDS` solely to force availability.

## 6. Free-data Market and Sector boundary

Current Free J-Quants does not provide eligible Market or Sector index OHLC for this design. v0.3.1 does not substitute another provider, scrape data, or build indices from constituents. Market/Sector quantitative context may therefore remain `null`; this means unavailable, not zero.

Company quantitative data remains v0.2. Paid J-Quants is a later-roadmap option, not a v0.3.1 dependency.

## 7. Optional Human enrichment

`news_taxonomy.json` is optional Human enrichment, not a ticker master. A ticker does not need an entry for `analyze` to proceed. Without enrichment, analysis can still use Company quantitative context, Market News, and Company News matched from J-Quants identity.

A ticker enrichment contains only:

```text
additional_aliases[]
sector_l1: string|null
sector_l2: string|null
themes[]
```

Sector/Theme News is added only when the corresponding enrichment exists. Both Sector fields may be `null`. A non-null L2 requires its coherent, defined L1 relationship in the simple taxonomy. Themes are controlled vocabulary IDs and must reference defined themes. v0.3.1 does not automatically classify a company into a KAIROS Sector or Theme.

Sector means the relatively stable business area in which a company operates. It has only L1 and L2; there is no L3. Theme means cross-cutting or time-varying investment, technology, policy, or demand exposure and is many-to-many. Avoid duplicating the same concept as both Sector and Theme when it adds no information. A company such as 9984 may legitimately have both Sector fields `null` while using Themes.

The seed taxonomy is provisional and Human-editable based on observed matching. Initial enrichment semantics are:

- 7203: Sector `automotive / automaker`; Themes `hv`, `ev`; additional aliases may include `トヨタ`, `Toyota`.
- 9984: no forced KAIROS Sector; Themes `ai`, `semiconductor`; additional aliases `ソフトバンクG`, `SBG`. Do not use the ambiguous `ソフトバンク` alone.
- 6857: Sector `semiconductor / semiconductor_equipment`; Themes `ai`, `semiconductor_test`, `hbm`, `hpc`; do not duplicate `semiconductor` as a Theme.

These values are starting enrichment choices, not universal truths.

When a new ticker is analyzed or an observed News classification problem requires it, the Human may update `news_taxonomy.json`. ChatGPT or another model may assist with proposing or reviewing the change. The Human reviews the Git diff and accepts the change by committing it. No separate proposal artifact or review machinery is required.

## 8. Minimal prospective News design

### 8.1 Source registry and raw record

The minimal source registry contains `name`, optional `source_id`, `url`, `default_layer`, and `enabled`. There are no source classes or plugins.

Each daily JSONL record under `DATA_ROOT/news/raw` contains only:

```text
source, published_at, retrieved_at, title, summary, url
```

This is a research record, not cache infrastructure. Duplicate storage identity is the canonical/item URL. One article is stored once even if it later matches several categories. If a verified feed later proves URL identity insufficient, handle that observed problem in a later change.

### 8.2 Matching and selection

The normal path is:

```text
stored RSS title + summary
  -> J-Quants company identity aliases + optional enrichment aliases
  -> optional sector/theme keywords
  -> deterministic Python matches
```

Latin company aliases and short Latin keywords use case-insensitive token/word-boundary matching; Japanese literals may use substring matching. There is no fuzzy, embedding, semantic, or model classifier in the normal path.

Broad official feeds such as central-bank and JPX market feeds use `default_layer` for Market News. One item may match multiple categories. For each relevant layer/category, select a compact recency top-N; N may be a small configuration value if needed. Before insertion into the later LLM context, deduplicate by URL across matches. That selection/integration deduplication is remaining work and is not claimed as part of the implemented Step 2 matcher. There is no importance, sentiment, direction, or other scoring engine.

Selected title, summary, source, publication time, URL, and matches are appended to the existing base analysis context. News is evidence, not causal proof.

### 8.3 Prospective-only and as-of rules

News is prospective only. RSS cannot reconstruct the `2026-06-30` historical information set, so v0.3.1 has no historical News backfill, simulation dataset, or News backtest using that date. Collection begins when the collector first runs.

A news item is usable only if both:

```text
published_at <= analysis_as_of
retrieved_at <= analysis_as_of
```

An analysis before collection began has no News. Because there is no post-hoc LLM extraction step, there is no extraction-time leakage. No News or no matching News means unavailable/no collected matching evidence; it never means that nothing happened.

## 9. Three-call analysis contract

All three calls use the OpenAI Responses API directly with Structured Outputs and no Web, tools, dynamic retrieval, or extra model call.

The base context contains common metadata, three-month `investment_horizon`, nullable Market/Sector quantitative context, selected Market/Sector/Theme/Company news, and v0.2 Company quantitative context.

- **Call 1 — Positive:** Fundamental, Valuation, and Bull analysis.
- **Call 2 — Independent Negative:** Bear and Risk analysis. It receives a base context identical to Call 1 and receives no Call 1 output, holding status, Thesis, or Recommendation.
- **Call 3 — Synthesis:** receives the same base context, Call 1, Call 2, and only deterministic `held` / `not_held` status from `portfolio.json`. It produces Contradictions, Unresolved Questions, Thesis, Invalidators, Expected Events, Recommendation, and Confidence.

Call 1 and Call 2 never receive holding information. Call 3 does not receive shares, acquisition cost, P/L, or holding duration. News may affect reasoning when relevant, but prompts must not present it as causal proof. Bull and Bear remain distinct rather than collapsing into one score.

Confidence remains `low / medium / high`, an allocation input rather than a precise probability.

## 10. Recommendation, Allocation, and Risk

For `not_held`, Recommendation is `BUY / WATCH / AVOID`; for `held`, it is `ADD / HOLD / REDUCE / SELL`. `WATCH` means positive interest but insufficient three-month evidence or risk/reward to initiate. `AVOID` means three-month risk/reward does not support initiation.

`REJECT` belongs only to deterministic Python Risk Check and is not an LLM Recommendation. Only `BUY` and `ADD` receive an Allocation calculation:

```text
allocation = configured_max_position * confidence_factor
confidence_factor: low=0.0, medium=0.5, high=1.0
```

Risk Check returns `PASS / REJECT` and enforces at least maximum single-position ratio, minimum cash ratio, no short selling, and established required-field presence for `BUY / ADD`. On `REJECT`, suggested allocation is none. Nullable optional Company/Market/Sector/News context alone does not reject an analysis, and BUY-only missing-data rules do not erase other recommendations.

`portfolio.json` is a Human-edited Risk/Allocation input, not portfolio management.

## 11. Report

Preserve the v0.2 report structure:

- Human View: Recommendation and main reason, strongest counterargument, Confidence, Suggested Allocation, Risk result, analysis/data dates, horizon, holding status;
- Company, available Market/Sector context, Calls 1–3, Allocation, and Risk details;
- Fundamental, Valuation, Bull, Bear, Risks, Contradictions, Unresolved Questions, Thesis, Invalidators, and Expected Events.

Add a concise **News Context Used** section listing source, publication date, title, and matched layer/sector/theme/company for the items actually sent to the model. Do not include raw JSON or full article bodies. Display `null` and absent news as unavailable/no collected matching evidence, not as zero or “nothing happened.”

## 12. Configuration, security, logging, and errors

Secrets stay in untracked `.env`; `.env.example` is tracked. Use `config.json` only for necessary non-secret settings. Never log API keys, secrets, or authorization headers.

Use standard Python logging with timestamp, level, operation, target, message, and exception. Classify failures only as needed—Configuration, J-Quants/external feed, Data, Model, Storage, Unexpected—and allow Human rerun rather than building retry state machines or recovery infrastructure.

## 13. Deterministic tests and evaluation

Retain v0.2 and implemented v0.3 tests. Permanent fixture-based coverage should include:

- RSS parsing/storage and storage URL deduplication;
- `published_at` and `retrieved_at` as-of boundaries;
- Company identity and optional alias matching, including case-insensitive Latin boundaries;
- optional/null Sector handling, coherent L1/L2 references, controlled Themes, and unknown tickers;
- Sector, Theme, Company, and Market `default_layer` matching;
- per-category top-N recency and URL deduplication before LLM context insertion;
- no-news behavior;
- identical Call 1/2 base context and Call 2 independence;
- Call 3 holding boundary;
- reporting only selected News context.

Permanent tests never depend on live RSS.

Prospective evaluation begins at collector start. For selected stocks, record analysis date, Recommendation, Confidence, Thesis, News context used, and the later three-month actual return. Require relevant News to affect the Thesis when appropriate, differentiated evidence/reasoning, no leakage, preservation of Company analysis when News is absent, and proof that `analyze` does not refetch RSS. Predictive validation requires elapsed forward observation; v0.3.1 starts that observation rather than proving three-month prediction immediately.

## 14. Explicit non-goals

- paid J-Quants, Reuters, paid News APIs, alternate market-data providers
- article-body crawling or scraping
- Jev, classifier models, LLM news preprocessing/extraction, or automatic Sector/Theme classification
- Event Store, rich schema, raw/event dual store
- importance, sentiment, or direction scoring
- custom Market/Sector indices
- all-stock screening, opportunity discovery
- portfolio management, Broker integration, automatic trading
- vector DB, RAG, daemon, internal scheduler
- periodic taxonomy review, unmatched-news aggregation, Structure Update commands, proposal schemas, reviewer agents, automatic taxonomy updates, or world-model machinery
- GDE, multi-agent systems
- database, dashboard, server, workflow engine, state machine, paper trading

## 15. Current implementation sequence and roadmap

After the v0.3.1 design is accepted, make one small implementation change: make ticker enrichment optional, allow null sectors, integrate verified J-Quants company identity, update seed enrichment aliases/sectors/themes, and preserve deterministic matching and tests. URL deduplication across selected matches belongs to later news selection/analyze integration if not yet applicable.

Later roadmap:

- **v0.4 Opportunity Discovery:** policy/investment trends -> Theme/Sector -> candidate companies
- **v0.5 Portfolio:** holdings/shares/acquisition cost/budget -> allocation/rebalance
- **v0.6+ Paid Data:** paid J-Quants and, only if justified, paid News/Reuters

This is planning direction, not a commitment; observations may change priorities.

## 16. Success criteria and final principle

v0.3.1 succeeds when it preserves the small v0.2 core, uses exactly six production modules and three fixed model calls, keeps Call 2 independent and holding context confined to Call 3, adds only as-of-safe prospectively collected News, treats J-Quants identity as the Company matching baseline and taxonomy entries as optional Human enrichment, tolerates unavailable Free-plan Market/Sector quantitative data, and produces an understandable report for Human decision-making.

Simple -> Working -> Useful -> strengthen only what observed use justifies.
