# KAIROS System Design v0.2

**Current Design Baseline — 2026-10-06**

| Item | Value |
|---|---|
| Baseline | v0.1の実装済み最小構成を維持し、v0.2の分析規則を段階導入する |
| Practical target | 3,000 LOC以下 |
| Hard ceiling | 10,000 LOC |
| Rule | 最小システム成立に不要なら削除。迷ったら削除。 |

---

## 1. 目的

KAIROSは、Humanが指定した1銘柄について投資判断を支援する小規模なローカルPythonアプリケーションである。

J-Quantsデータを取得して調査記録としてraw保存し、情報条件を揃えた独立した強気分析と弱気・Risk分析を行う。続いて矛盾、Thesis、Invalidator、Recommendationを統合し、決定論的なAllocation / Risk Checkを通したMarkdown Investment Reportを出力する。

最終投資判断とBroker操作はHumanが行う。KAIROSは自動売買しない。

## 2. 設計原則と非目的

1. v0.1の5 module、3 call、固定Python pipelineを維持する。
2. 手動操作で代替できるものは原則自動化しない。
3. 将来必要になる可能性だけでは機能、module、抽象化を追加しない。
4. Structured Outputsを使用し、AllocationとRisk Checkの最終判定は決定論的Pythonで行う。
5. raw archiveは調査記録でありcacheではない。

実装しないもの:

- Broker API、自動売買、scheduler、screening、database、dashboard、server
- 分散Agent、Agent hierarchy、Agents SDK、Handoff、Model Router、workflow engine
- context class、domain type hierarchy、`models.py`、data platform
- position lifecycle / state machine、order lifecycle、portfolio update command
- backtest system、PIT基盤、historical replay、paper trading system、virtual portfolio
- trust、closure、approval、durable stage、自動recovery等の運用機構

旧ARGUSおよび旧chatgpt-agentの設計・機構は使用しない。

## 3. 最小Vertical Sliceとシステム構成

```text
Human ticker指定
  → J-Quantsデータ取得・as-of適用
  → raw調査データをDATA_ROOTへ保存
  → research_data整形
  → Call 1: Fundamental / Valuation / Bull
  → Call 2: Bear / Risk
  → Call 3: Contradiction / Thesis / Invalidator / Recommendation
  → 決定論的Allocation
  → 決定論的Risk Check
  → Markdown Investment Report
  → Human Decision
```

単一Python applicationとし、production moduleは次の5つを維持する。

- `main.py`: argparse、`.env` / config、logging、`analyze`、処理順制御
- `data.py`: J-Quants取得、as-of適用、最低限の整形、raw保存
- `llm.py`: 3回のModel call、prompt、JSON Schema
- `risk.py`: `portfolio.json`読込、Allocation式、Risk rule
- `report.py`: Markdown Investment Report生成

`tests/`にはVertical Slice、Risk、data parsingの最低限のtestだけを置く。役割以上にファイルを分割せず、共通化は実際にコード量を減らす場合だけ行う。

## 4. 起動、as-of、データ鮮度

```text
python main.py analyze 7203
python main.py analyze 7203 --as-of 2026-06-30
```

`--as-of`なしでは利用可能な最新データを使用する。指定時はJ-Quantsから取得したデータのうち`analysis_as_of`以前に利用可能なものだけを分析入力に使用する。実際に使用したデータの基準日を`data_as_of`として保持しReportへ出力する。

`--as-of`はHistorical Sanity Check用の最小機能であり、厳密なPoint-in-Time Backtest、Out-of-Sample Test、投資性能証明ではない。LLMが学習済みの未来情報を持つ可能性を排除する基盤は作らない。

J-Quantsの契約planにより取得期間、更新時刻、遅延が異なり得るため、特定の遅延日数を設計へ固定しない。J-Quants Freeの遅延はv0.2の設計driverとしない。v0.2では基本機能を確立し、有料J-Quantsの利用はv0.3〜v0.4頃を想定する。

## 5. 調査データとraw保存

データ源はJ-Quantsに限定し、既に取得・保存しているJ-Quantsデータを追加providerより先に活用する。API全体を抽象化せず、実際に必要なendpointだけを扱う。

取得したrawはDATA_ROOTへ保存する。目的は再現可能な調査記録でありcacheではない。保存済みrawを鮮度判定してAPI callを省略する機構は作らない。

`research_data`は次のsimple nested `dict`とする。

```text
research_data = {
  metadata: {...},
  market: {...} | null,
  sector: {...} | null,
  company: {...}
}
```

これはデータ整理だけであり、context class、新production module、agent hierarchy、data platformを導入しない。存在しない任意データは`null`とし、空配列や架空の値で埋めない。

## 6. 投資Horizon

標準`investment_horizon`は3か月とする。これは評価およびRecommendationのhorizonであり、強制保有期間、自動売却期限、position lifecycleではない。

重大なevent、新たな決算、Thesis invalidation、またはhorizon到来時は、Humanが再分析を判断できる。KAIROSは自動監視、自動再分析、自動売却を行わない。

## 7. 3-call LLM分析

OpenAI Python SDKからResponses APIを直接使い、3 callすべてでStructured Outputsを使用する。3 callは同一modelを使用してよい。動的Tool選択や追加調査は行わない。

### 7.1 Call 1 — Positive Analysis

Call 1はbase research context、`analysis_as_of`、`data_as_of`、`investment_horizon`を受け、Fundamental、Valuation、Bull caseを分析する。

### 7.2 Call 2 — Independent Negative Analysis

Call 2はCall 1と完全に同一のbase research context、`analysis_as_of`、`data_as_of`、`investment_horizon`を受け、Bear caseとRiskを分析する。

Call 2へCall 1の出力、結論、Recommendation、Thesis、推論結果を一切渡さない。Call 1とCall 2は外部検索や追加データ取得を行わない。

### 7.3 Call 3 — Synthesis

Call 3は次を受け取る。

- Call 1/2と同じresearch contextおよび共通metadata
- Call 1の出力
- Call 2の出力
- `portfolio.json`から決定論的に導出した対象銘柄の最小`held` / `not_held` fact

保有数量、取得価額、損益、保有期間等はCall 3へ渡さない。Call 3はContradictions、Unresolved Questions、Thesis、Invalidators、Expected Events、Recommendation、Confidenceを生成する。Bull / Bearを単純平均して単一scoreへ潰さない。

Call 1とCall 2には保有状態を渡さない。したがってbase investment assessmentの独立性を保ち、Call 3だけが適切なRecommendation vocabularyを選択する。

### 7.4 Confidence

Confidenceは`low / medium / high`のenumとし、精密な確率を意味しない。Allocation計算用の離散区分として扱う。

## 8. Recommendation

Recommendationは3か月horizonにおける投資評価である。

対象銘柄が`not_held`の場合:

```text
BUY / WATCH / AVOID
```

対象銘柄が`held`の場合:

```text
ADD / HOLD / REDUCE / SELL
```

- `WATCH`: 投資上のpositiveな関心はあるが、3か月で新規投資を開始するには証拠またはrisk/rewardが不十分。
- `AVOID`: 3か月のrisk/rewardが新規投資開始を支持しない。

`REJECT`はLLM Recommendationではない。`REJECT`は決定論的Python Risk Checkだけの結果である。

Recommendationは投資評価、Risk Checkはallocation / execution eligibilityであり、両者を混同しない。Recommendationからposition lifecycleやstate machineを作らない。

## 9. Company context

Company contextは、analysis時点で利用可能な既取得・保存済みJ-Quants rawから、存在するものだけをcompactに整形する。

### 9.1 Snapshot

候補はprice、revenue、operating profit（OP）、net profit（NP）、equity ratio、PERとする。

### 9.2 Historical comparable trend

比較は同一period typeの前年同期だけとする。

- FY と prior FY
- 1Q と prior-year 1Q
- 2Q cumulative と prior-year 2Q cumulative
- 3Q cumulative と prior-year 3Q cumulative

periodが異なる単なる前回開示とは比較しない。各metricは`current`、`prior_comparable`、および有効な場合だけ`change`または`change_pct`を持つ。

候補metricはrevenue、OP、NP、operating margin、net margin、equity ratio、EPSとする。ROEは直接適切なlatest full-year valueだけを使い、四半期値のannualizationを発明しない。

### 9.3 Cash flow

rawに実在する場合だけOCF、ICF、FCF、cash equivalentsを候補とする。CFとNPの比較はperiodがcompatibleな場合だけ行い、それ以外は`null`とする。

### 9.4 Company forecast

実装時に保存済みrawの実field名とsemanticsを先に確認する。`analysis_as_of`時点で利用可能な、関連するcurrent fiscal year outlookを表すlatest forecastを選ぶ。

候補はforecast revenue、OP、NP、EPS、dividendとする。forward PERは有効なforecast EPSとas-of-safe priceがある場合だけ算出してよい。current-periodとnext-periodのforecast semanticsを混在させない。

### 9.5 Price trend

`Date <= analysis_as_of`のadjusted closeを使い、21 / 63 / 126 / 252 trading-observation return（約1か月 / 3か月 / 6か月 / 1年）をcompactに保持する。full OHLC historyはLLMへ渡さない。履歴不足は`null`とする。

### 9.6 Missing data

missingまたはemptyは常に`null`とし、zeroへ変換しない。Promptは`null`をunavailableとして扱う。

これらは任意contextであり、追加のためだけにv0.1の`REQUIRED_FIELDS`を拡張しない。field名、forecast semantics、CF availability等は未検証として扱い、実装時にraw/APIを確認して決定する。

## 10. Market / Sector context

Marketは、選択したJ-Quants plan/APIから直接利用可能なindex dataだけを使う。TOPIXを第一候補とする。Nikkei 225はproviderを追加せず直接利用可能な場合だけ使う。

SectorはJ-Quantsから直接利用可能なsector / industry index dataだけを使う。利用できなければ実装せずBACKLOGへ記録する。構成銘柄からcustom sector indexを作らない。

Market / Sector contextはcompactなcurrent、trend、relative-performance factsとし、raw historyをLLMへ渡さない。company-vs-sectorおよびsector-vs-market relative performanceは、直接利用可能でperiod-alignedな場合だけ生成する。

indexおよびfieldのavailabilityは設計時点で断定せず、実装時に選択planのAPI/rawを確認する。

## 11. Newsの将来境界

Newsはv0.2実装対象外である。`research_data`へ空のnews arrayやplaceholderを追加しない。crawler、provider、database、sentiment、scoring、Web pipelineを作らない。

将来導入する場合の概念上の配置だけを次のように定める。

- Market news: 日本・米国・中国・欧州の政府、中央銀行、経済、金融、conflict、major disaster
- Sector news: major investment、technology / invention、regulation、supply / demand
- Company news: investment、products、earnings / guidance、M&A / alliances、material company events

Historical useでは必ず`published_at <= analysis_as_of`を要求する。

## 12. Portfolio、Allocation、Risk Check

`portfolio.json`はRisk / Allocation計算の入力とし、Call 3向けの最小`held` / `not_held` factの導出にも使う。Humanが直接編集してよい。Call 1/2には使用しない。

Allocationを計算するRecommendationは`BUY`と`ADD`だけとする。Confidence factorは`low=0.0`、`medium=0.5`、`high=1.0`とし、例として次の単純式を使う。

```text
allocation = configured_max_position × confidence_factor
```

LLMにallocation比率を決めさせない。

Risk CheckはPythonの単純なrule functionとし、結果は`PASS / REJECT`とする。最低限、1銘柄最大保有比率、最低現金比率、空売り禁止、`BUY / ADD`時のv0.1 `REQUIRED_FIELDS`欠損を判定する。`REJECT`なら`suggested_allocation = none`とする。

任意のv0.2 company / market / sector contextが`null`であることだけを理由にRisk Checkを`REJECT`にしない。`WATCH / AVOID / HOLD / REDUCE / SELL`という投資評価をBUY用の欠損ruleで消さない。

## 13. Investment ReportとHuman Decision

Report先頭のHuman Viewには最低限次を表示する。

- Recommendationと主要理由
- 最大の反対理由
- Confidence
- Suggested Allocation
- Risk Check結果
- Analysis as-of / Data as-of / Investment horizon
- Held / Not held

詳細にはCompany、利用できる場合のMarket / Sector、Fundamental、Valuation、Bull、Bear、Risk、Contradictions、Unresolved Questions、Thesis、Invalidators、Expected Eventsを含める。`null`はunavailableとして表示し、zeroのように扱わない。

ReportはHuman判断用artifactでありBroker commandではない。Humanが最終投資判断とBroker操作を行い、必要なら`portfolio.json`を直接更新する。

## 14. Configuration、Logging、Error Handling

Secretは`.env`へ置きGit管理しない。`.env.example`をGit管理する。非secret設定が必要な場合だけ`config.json`を使用する。

Python標準loggingを使用し、timestamp、level、operation、target、message、exceptionを記録する。secret、API key、authorization headerは記録しない。

ErrorはConfiguration、J-Quants / External API、Data、Model、Storage、Unexpected程度に分類し、log、Human向けmessage、必要なら終了とする。複雑なretry state machineや自動recoveryは作らずHuman再実行を許容する。

## 15. TestとHistorical Sanity Check

Software testはstub end-to-end Vertical Slice、`risk.py` rule、J-Quants response parsing、発見済みbugのregressionを優先する。巨大test matrixやvalidation frameworkは作らない。

Historical Sanity Checkは判断logicの明らかな問題を見つけるための手動評価であり、backtestや収益性証明ではない。

v0.2は次の順序で段階実装・評価し、すべてを一度に実装しない。

1. **Step A — Horizon + Recommendation**: 3か月horizon、保有状態の入力境界、新Recommendation vocabularyを実装し、7203 / 9984 / 6857を`2026-06-30`で再実行する。
2. **Step B — Company Context**: historical comparable trend、cash flow、forecast、price trendを追加し、同じ3銘柄・基準日で再実行する。
3. **Step C — Market / Sector**: architectureを拡張せずJ-Quantsから直接supportされる場合だけ追加し、同じ3銘柄・基準日で再実行する。

目的は、`WATCH / MEDIUM`への収束がRecommendation semantics、company evidence、broader contextのどの段階で変化するかを区別することである。

各段階でCall 2 independence、as-of制約、Recommendation vocabulary、`null` semantics、deterministic Allocation / Risk境界を確認する。

## 16. Repository構成と制約

```text
C:\dev\kairos
├─ main.py
├─ data.py
├─ llm.py
├─ risk.py
├─ report.py
├─ .env.example
├─ config.json
├─ requirements.txt
├─ BACKLOG.md
├─ data/
│  └─ portfolio.json
├─ reports/
├─ logs/
├─ tests/
└─ docs/
   └─ kairos_system_design_v0.2.md
```

10,000 LOCをhard ceiling、3,000 LOC以下を実質目標とする。新機能、工程、抽象化がこの制約または5 module構成を壊す場合は削除・単純化する。

## 17. 成功条件

KAIROS v0.2は次を満たす。

- 5 moduleの固定Python pipelineと3 fixed model callsを維持する。
- Call 1/2へ同一base contextを渡し、Call 2 independenceを維持する。
- 3か月horizonと保有状態別Recommendationを一貫して適用する。
- `REJECT`をdeterministic Risk Checkだけに限定する。
- 既存J-Quantsデータを安全なperiod比較と`null` semanticsで段階的に活用する。
- Market / Sectorは直接利用可能な場合だけ扱い、custom indexを作らない。
- News pipelineを実装しない。
- HumanがReportを理解し、最終判断とBroker操作を行える。

## 18. 最終原則

KAIROS v0.2はv0.1の小さく動くarchitectureを置換しない。分析規則と利用contextを、A → B → Cの順に検証可能な単位で強化する。

Simple → Working → Useful → 必要になった部分だけ強化。

Humanによる再実行、設定変更、`portfolio.json`直接編集、手動評価を正常な運用方法として許容する。複雑さを追加して自動化するより、Humanが理解し操作できる単純な方法を選ぶ。
