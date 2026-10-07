# KAIROS System Design v0.3.2

**Current Design Baseline — 2026-10-07**

## 1. Purpose and boundary

KAIROS is a small local Python application that improves three-month investment decisions for one stock specified by the Human. v0.3.2 preserves the v0.2 Company-analysis core and the prospective v0.3 News design, and adds one narrowly scoped next step: enrich RSS observations with article HTML content because RSS titles and summaries can be insufficient.

v0.3.2 authorizes article HTML content enrichment and defines how that content will later support deterministic matching. It does not yet implement `news-enrich`, News selection in `analyze`, News-to-three-call integration, semantic analysis, an LLM News summary or classifier, or PDF extraction.

KAIROS does not discover stocks, manage a portfolio, or use paid data. It produces a Markdown research report; the Human makes the final investment decision and performs any Broker operation. Keep the system under 3,000 LOC where practical, with 10,000 LOC as a hard ceiling. Do not add an abstraction or module until observed use requires it.

## 2. Evidence and current baseline

At `2026-06-30`, the v0.2 evaluation produced stable but limited differentiation: after Company Context, 7203 was `AVOID / MEDIUM` in three runs, while 9984 and 6857 were `WATCH / MEDIUM` in three runs. Company quantitative analysis, three fixed model calls, deterministic Allocation/Risk, and the report remain the core.

The current v0.3 implementation has:

- manual `news-update` collection from the verified BOJ and Federal Reserve RSS sources;
- UTF-8 raw daily JSONL with URL deduplication;
- deterministic Company/Sector/Theme matching using J-Quants company identity and optional Human taxonomy enrichment;
- no News selection, analysis integration, or News reporting yet.

Live collection returned more than 70 BOJ items and 15 Federal Reserve items; a second run recognized all 85 as duplicates. The BOJ RSS summaries were effectively empty. Against the same eight RSS-captured article URLs, Trafilatura 2.3.1 on Python 3.14.7 extracted all eight, while newspaper4k 0.9.6 extracted the four Federal Reserve pages but none of the four BOJ pages in a minimal installation because of a Japanese tokenizer dependency. Trafilatura generally produced useful bodies. One BOJ speech landing page was mostly navigation because the full speech was in a linked PDF. This evidence selects Trafilatura for normal HTML extraction and defers PDF support.

## 3. Fixed pipeline and six modules

```text
Manual news-update
  -> verified RSS metadata only
  -> DATA_ROOT/news/raw/YYYY-MM-DD.jsonl

Future manual news-enrich
  -> raw URLs not represented in the content store
  -> normal HTML fetch + Trafilatura main-text extraction
  -> DATA_ROOT/news/content/YYYY-MM-DD.jsonl

Human-specified ticker -> analyze
  -> J-Quants acquisition, as-of filtering, raw archive
  -> verified company identity + optional Human enrichment
  -> three existing model calls
  -> deterministic Allocation and Risk Check
  -> Markdown Investment Report -> Human decision
```

The production modules remain exactly:

- `main.py`: argparse, `.env` / config, logging, commands, orchestration
- `data.py`: J-Quants acquisition, as-of filtering, compact shaping, raw archive
- `news.py`: News registry/taxonomy validation, RSS retrieval/parsing, raw/content persistence, deterministic matching and later selection
- `llm.py`: three model calls, prompts, JSON Schemas
- `risk.py`: `portfolio.json`, Allocation, Risk rules
- `report.py`: Markdown Investment Report

Do not split HTML extraction, RSS, crawler, classifier, taxonomy, or event concerns into additional production modules.

## 4. Commands and network boundary

The established interface remains:

```text
python main.py analyze 7203
python main.py analyze 7203 --as-of 2026-06-30
python main.py news-update
```

`news-update` remains RSS metadata only: it fetches enabled feeds and stores new URL-unique raw observations. It never fetches article bodies.

A future manual `news-enrich` command will read stored raw observations, fetch only RSS-captured URLs absent from the content store, extract the main text from normal HTML with Trafilatura, and persist one terminal success or failure observation per URL. It does not exist in the current implementation.

`analyze` never fetches RSS, article HTML, PDFs, or other Web content. There is no KAIROS scheduler or daemon. External scheduling may be considered later but is not part of v0.3.2.

## 5. News stores and identity

The two stores are:

```text
DATA_ROOT/news/raw/YYYY-MM-DD.jsonl
DATA_ROOT/news/content/YYYY-MM-DD.jsonl
```

Raw is the existing RSS observation, with exactly:

```text
source, published_at, retrieved_at, title, summary, url
```

Content is a later HTML-body retrieval observation, not an Event Store, cache framework, or replacement for Raw. URL is the identity in both stores. At the current scale, `news-enrich` scans existing content JSONL files to build the set of already observed URLs.

A successful UTF-8 JSONL content record has exactly:

```text
url, content_retrieved_at, status: "success", text
```

A failed record has exactly:

```text
url, content_retrieved_at, status: "failed", error
```

Daily content filenames use the UTC calendar date of `content_retrieved_at`. Timestamps are timezone-aware ISO 8601 values normalized to UTC.

## 6. Enrichment access, pacing, and failure behavior

Only URLs captured by configured RSS feeds are eligible. `news-enrich` does not follow article links, recursively crawl, accept arbitrary URLs, run a JavaScript browser, bypass paywalls, or fetch a linked PDF. Trafilatura is used only for a normal HTML request and main-text extraction.

Use a short fixed delay between consecutive article requests, especially requests to the same host. This is a simple courtesy delay, not a rate-limiter framework. Before adding any future media source, verify both its feed terms and permission to fetch and store article bodies; permission to consume a feed does not by itself establish body-storage permission.

Both successful and failed URLs already present in the content store are skipped. Persisting a failure prevents implicit infinite retries and repeated hits. A Human may retry deliberately by removing the failed record; there is no retry queue, backoff state, or automatic retry machinery.

Processing is best-effort per article. One failure does not invalidate its Raw observation and does not discard other successes. The command reports concise `processed`, `success`, `already`, and `failed` counts and logs each failure with its URL and error without logging article bodies or secrets.

## 7. Dependency decision

v0.3.2 narrowly authorizes Trafilatura as a production dependency for HTML fetching and main-text extraction, based on the eight-page proof of concept. newspaper4k is not selected. This design update does not install either package or change requirements or configuration.

PDF extraction remains explicitly deferred. The noisy BOJ speech landing page shows why PDF frequency should be observed prospectively before adding another acquisition path or dependency.

## 8. Prospective time and leakage rules

News remains prospective only. RSS cannot reconstruct the historical information set before collection began; there is no historical News backfill or News backtest.

The relevant times are:

- `published_at`: source publication time from RSS
- `retrieved_at`: time KAIROS observed the RSS item
- `content_retrieved_at`: time KAIROS retrieved and extracted the article HTML

A body is eligible only when all three timestamps are at or before `analysis_as_of`:

```text
published_at <= analysis_as_of
retrieved_at <= analysis_as_of
content_retrieved_at <= analysis_as_of
```

If content was retrieved too late, the Raw title and summary may still be used when their own `published_at` and `retrieved_at` cutoffs pass. A failed or absent content record never invalidates eligible Raw metadata. No News or no matching News means unavailable/no collected matching evidence, not that nothing happened.

## 9. Deterministic excerpt and matching

For an eligible successful content record, derive the excerpt as the first 600 characters of `text`. Do not store the excerpt separately. The same deterministic first-600-character excerpt is used both for matching and, later, for compact LLM News context.

Matching input is:

```text
title + summary + excerpt   when eligible content exists
title + summary             otherwise
```

Matching remains deterministic. Latin aliases and keywords use Unicode normalization, case-insensitive comparison, and token/word boundaries; Japanese literals use normalized literal substring matching. There is no fuzzy matching, semantic score, embedding, or model classifier.

J-Quants company identity supplies baseline Japanese and actually available English company names. Optional `news_taxonomy.json` enrichment supplies additional aliases, nullable KAIROS Sector L1/L2, and controlled Themes. A ticker does not require a taxonomy entry. Do not invent identity fields, force sector membership, or collapse Sector and Theme.

An item's source `default_layer=market` establishes Market membership without requiring a keyword match. Company, Sector, and Theme matches may be added to the same item and never replace its Market membership.

## 10. Company, Market, Sector, and taxonomy continuity

The v0.2 Company context remains unchanged: as-of-safe J-Quants snapshot, comparable financial history, margins and supported metrics, compatible cash flow, forecast, and 21/63/126/252-observation price trends. Missing data remains `null`, never an invented value or zero. Optional context does not expand established required fields merely to force availability.

Free J-Quants still does not supply eligible Market or Sector index OHLC for this design. Those quantitative contexts may remain `null`; v0.3.2 does not scrape substitutes or build constituent indices. Paid J-Quants remains a later option.

The current optional Human taxonomy and J-Quants identity model remain valid. Sector has L1/L2 only, Theme is controlled and many-to-many, and an absent ticker enrichment disables only its Sector/Theme matching. Human-reviewed JSON changes are sufficient; no proposal workflow, taxonomy agent, or automated taxonomy update is added.

## 11. Future News selection and three-call contract

v0.3.2 implements only the content-enrichment and excerpt/matching contract. Later integration follows this fixed order:

```text
Raw + Content
  -> as-of filtering
  -> deterministic relevance using title + summary + derived excerpt
  -> recency top-N per relevant category
  -> cross-category URL deduplication
  -> compact News Context
  -> existing three calls
  -> report
  -> prospective observation
```

Later selected News context contains only compact fields: `source`, `published_at`, `title`, the same derived excerpt, matched layer/sector/theme/company, and URL when appropriate. Never send the full article body to a model. Do not create an LLM News summary.

All three calls continue to use the OpenAI Responses API directly with Structured Outputs and no Web, tools, dynamic retrieval, or extra model call:

- Call 1 — Positive: Fundamental, Valuation, and Bull analysis.
- Call 2 — Independent Negative: Bear and Risk analysis. It receives the same base context as Call 1 and no Call 1 output, holding status, Thesis, or Recommendation.
- Call 3 — Synthesis: the same base context, Calls 1 and 2, and only deterministic `held` / `not_held` status. It produces Contradictions, Unresolved Questions, Thesis, Invalidators, Expected Events, Recommendation, and Confidence.

Calls 1 and 2 never receive holding information. Call 3 never receives shares, acquisition cost, P/L, or holding duration. News is evidence, not causal proof. Bull and Bear remain distinct, and Confidence remains `low / medium / high` rather than a probability.

## 12. Recommendation, risk, and report continuity

The v0.2 recommendation sets remain `BUY / WATCH / AVOID` for `not_held` and `ADD / HOLD / REDUCE / SELL` for `held`. `REJECT` belongs only to deterministic Risk Check. Only `BUY` and `ADD` receive allocation:

```text
allocation = configured_max_position * confidence_factor
confidence_factor: low=0.0, medium=0.5, high=1.0
```

Risk Check remains deterministic and enforces maximum single-position ratio, minimum cash ratio, no short selling, and established required-field presence for `BUY / ADD`. Missing optional Company/Market/Sector/News context alone does not reject an analysis. `portfolio.json` remains a Human-edited Risk/Allocation input, not portfolio management.

Preserve the v0.2 report. When News integration is implemented later, add a concise **News Context Used** section for only the compact items actually sent to the model; never include raw JSON or full article bodies.

## 13. Tests required with implementation

Retain all existing v0.2 and v0.3 tests. The future implementation has offline fixture-based coverage for at least:

- useful Japanese and English HTML extraction;
- a successful URL is not fetched again;
- a failed URL is persisted and is not fetched again;
- one extraction failure leaves Raw intact and does not discard other successes;
- matching uses the first 600 characters of eligible content and falls back to Raw metadata when content is absent, failed, or too late;
- `published_at`, `retrieved_at`, and `content_retrieved_at` cutoffs;
- Market membership from `default_layer` without keyword matching;
- existing Latin boundary/case-insensitive and Japanese literal matching behavior.

Permanent tests never depend on live RSS or live article pages. This design-only change adds or runs no implementation tests.

## 14. Explicit non-goals

- PDF retrieval or extraction; recursive crawling; arbitrary-URL crawling; JavaScript browser automation; paywall bypass
- newspaper4k or a newspaper-specific parser
- LLM/Jev News classification, extraction, or summary; semantic classification or scoring
- full article-body model input; sentiment, importance, direction, or causal scoring
- News selection or `analyze`/three-call/report integration in this step
- Event Store, cache framework, database, embeddings, vector DB, or RAG
- paid News/Reuters, paid J-Quants, alternate market-data providers
- scheduler, daemon, retry service, workflow engine, or state machine
- custom Market/Sector indices, all-stock screening, opportunity discovery
- portfolio management, Broker integration, automatic trading, paper trading
- automatic taxonomy updates, reviewer agents, multi-agent systems, or world-model machinery

## 15. Remaining sequence and roadmap

The immediate implementation sequence after design acceptance is only: add `news-enrich`, the content store, Trafilatura HTML extraction, terminal success/failure persistence, pacing, logging/counts, and deterministic excerpt-aware matching with offline tests.

The remaining News sequence is:

```text
Raw + Content -> as-of -> deterministic relevance/excerpt -> top-N
  -> URL dedup -> compact News Context -> three calls -> report
  -> prospective observation
```

Later roadmap remains v0.4 Opportunity Discovery, v0.5 Portfolio, and v0.6+ paid data only if observations justify them. This is direction, not a commitment.

## 16. Success criterion and final principle

v0.3.2 succeeds when it preserves the small v0.2 core, exactly six production modules, exactly three fixed model calls, Call 2 independence, and holding context confined to Call 3; keeps News prospective and fully as-of-safe; preserves J-Quants identity plus optional taxonomy enrichment and deterministic matching; and adds only a bounded, permission-aware path from RSS-captured URLs to stored HTML main text and a shared 600-character excerpt—without claiming unimplemented News analysis integration.

Simple -> Working -> Useful -> strengthen only what observed use justifies.
