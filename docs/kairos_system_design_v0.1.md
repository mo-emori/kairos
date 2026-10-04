# KAIROS System Design v0.1

**Final Design Baseline — 2026-10-05**

| Item | Value |
|---|---|
| Implementation | 約1週間 |
| Practical target | 3,000 LOC以下 |
| Hard ceiling | 10,000 LOC |
| Rule | 最小システム成立に不要なら削除。迷ったら削除。 |

---

## 1. 目的

KAIROSは、人間の投資判断を支援する小規模なローカルPythonアプリケーションである。

v0.1は、Humanが指定した1銘柄についてデータを取得し、独立した強気分析と弱気・Risk分析を行い、矛盾を抽出し、Thesis・Invalidator・Recommendationを生成し、決定論的Allocation / Risk Checkを通したInvestment Reportを出力する。

最終投資判断とBroker操作はHumanが行う。KAIROSは自動売買しない。

---

## 2. 設計原則

1. その機能がなければ最小システムが成立しない → 残す。
2. なくても成立する → 削除。
3. 判断に迷う → 削除。
4. 手動操作で代替できる → 原則自動化しない。
5. 将来必要になる可能性だけでは追加しない。
6. 追加アイデアはBACKLOG.mdへ記録し、v0.1へ入れない。
7. 複雑な開発工程・承認工程・closure・trust機構を導入しない。
8. Day 2終了までにstubでもend-to-endを通す。

---

## 3. v0.1 非目的

実装しないもの:
自動売買、Broker API、Selection / Screening、Universe / Candidate Pool、EDINET client、独自Web Provider、portfolio update command、watch command、独自Scheduler、raw data cache・再利用判定、Database、Dashboard、Tray UI、Server / VPS、分散Agent、Message Queue、Bootstrap Orchestrator、Runtime Identity、Environment Binding、Runner lifecycle state machine、Durable Stage、自動Recovery、Backup / Restore機構、Storage identity / marker検証、Storage容量監視、Storage縮退制御、Service Registry、Paid Service Governance、Budget reservation、多階層Budget Gate、Decision Queue、User Status / BUSY Lease、Alert / Incident / Notification state machine、Notification Window、Break B1〜B4、CV / RV体系、Contract文書群、validation package、trust baseline / candidate / promotion、authority reconciliation、capability closure、review ceremony、models.py。

安全性、将来拡張、完全性を理由としてv0.1へ復活させない。

投資判断検証のための以下の機構も実装しない。

- Backtest system
- PIT Historical Data基盤
- Historical Replay framework
- Paper Trading system
- Virtual Portfolio
- 仮想Order / Execution管理
- Performance tracking機構
- 価格追跡Job

検証のために別の大規模システムを作らない。

---

## 4. 最小Vertical Slice

Human ticker指定
→ J-Quantsデータ取得
→ raw調査データを外付けHDDへ保存
→ Call 1: Fundamental / Valuation / Bull
→ Call 2: Bear / Risk
→ Call 3: Contradiction / Thesis / Invalidator / Recommendation
→ 決定論的Allocation
→ 決定論的Risk Check
→ Markdown Investment Report
→ Human Decision

Call 2にはCall 1の出力・結論を渡さない。同一の調査データだけを入力する。Call 3だけがCall 1とCall 2の双方を受け取る。

---

## 5. システム構成

単一Python applicationとし、Bootstrap layerは作らない。

main.py — argparse、.env/config、logging、analyze command、処理順制御
data.py — J-Quants取得、最低限の整形、raw保存
llm.py — 3回のModel call、prompt、JSON Schema
risk.py — portfolio.json読込、Allocation式、Risk rule
report.py — Markdown Investment Report生成
tests/ — Vertical Slice、Risk、data parsingの最低限test

役割以上にファイルを分割しない。共通化は実際にコード量を減らす場合だけ行う。

---

## 6. 起動

基本Command:

```text
python main.py analyze 7203
```

Historical Sanity Checkでは、任意の基準日を指定できる。

```text
python main.py analyze 7203 --as-of 2025-06-30
```

処理順序:

```text
.env読込
  ↓
config読込
  ↓
logging初期化
  ↓
ticker検証
  ↓
J-Quantsデータ取得
  ↓
as-of適用
  ↓
raw保存
  ↓
3-call分析
  ↓
Allocation / Risk Check
  ↓
Report生成
  ↓
終了
```

`--as-of`を指定しない場合は、J-Quantsから利用可能な最新データを使用する。

`--as-of YYYY-MM-DD`を指定した場合は、取得したJ-Quantsデータのうち、指定日以前のデータだけを分析入力として使用する。

`--as-of`はHistorical Sanity Checkのための最小機能であり、Historical Replay Framework、PIT Provider、Backtest Engineを構築するものではない。

独自Runner、daemon、scheduler、bootstrap、lifecycle管理は作らない。

再分析はHumanが`analyze`を再実行する。

---

## 7. Configuration / .env

Secretは.envへ置き、Git管理しない。.env.exampleをGit管理する。

OPENAI_API_KEY=
JQUANTS_API_KEY=
DATA_ROOT=

非Secret設定が必要な場合だけconfig.jsonを使用する。Configuration Writer、version、hash、snapshotは作らない。設定不備はログと画面へ出して終了する。

---

## 8. Data Acquisition

v0.1のデータ源はJ-Quantsに限定する。

分析に必要な財務データと株価データの最小集合だけ取得する。

J-Quants API全体を抽象化しない。v0.1の分析に実際に必要なendpointだけ実装する。

Web検索はv0.1では使用しない。

EDINET、News Provider、独自Web Provider、crawler、Web検索Toolはv0.1対象外とする。

これにより、Call 1とCall 2には同一のJ-Quants調査データを入力する。

```text
              J-Quants dataset
                 /        \
                /          \
           Call 1          Call 2
                \          /
                 \        /
                   Call 3
```

Call 1とCall 2が独立して追加情報を取得することを禁止する。

`--as-of`指定時には、指定日より後のJ-Quantsデータを分析入力へ含めない。

LLM自身が学習済みの未来情報を持つ可能性を排除する仕組みはv0.1では作らない。このため`--as-of`による分析を厳密なPoint-in-Time BacktestまたはOut-of-Sample Testとして扱わない。

J-Quantsの契約Planによって利用可能なデータ期間、更新時刻、遅延等が異なる可能性があるため、特定の遅延日数をKAIROS設計へ固定しない。

KAIROSは実際に分析へ使用したデータの基準日を`data_as_of`として保持し、Reportへ出力する。

J-Quantsだけでは分析品質が不足すると実運用で確認された場合、追加データ源を`BACKLOG.md`で検討する。

---

## 9. 調査データ保存

取得した調査データは外付けHDDのDATA_ROOTへ保存する。保存目的は調査記録でありcacheではない。保存済みrawを読み戻してAPI callを省略する鮮度判定・cache機構は持たない。

Storage identity、marker、drive検証、容量監視、保存先検証、縮退制御は行わない。保存失敗はStorage Errorとしてまとめてよい。

---

## 10. LLM分析

KAIROS v0.1のLLM分析には、OpenAI Python SDKからResponses APIを直接使用する。

Agents SDKは使用しない。

Jev等のDecision Model / Routing Modelも使用しない。

v0.1の処理順序は固定されており、Agentによる動的なTool選択、Handoff、Routing、次処理判断を必要としない。

LLM処理は`llm.py`から3回のModel Callとして直接実行する。

```text
                  J-Quants dataset
                       │
             ┌─────────┴─────────┐
             ↓                   ↓
          Call 1              Call 2
     Positive Analysis   Negative Analysis
             │                   │
             └─────────┬─────────┘
                       ↓
                    Call 3
                   Synthesis
                       ↓
               Structured Result
```

### 10.1 Call 1 ? Positive Analysis

入力:

- 同一のJ-Quants調査データ
- `analysis_as_of`
- `data_as_of`

主として以下を分析する。

- Fundamental
- Valuation
- Bull case

出力には分析結果とその根拠を含める。

Call 1から外部Web検索や追加データ取得を行わない。

### 10.2 Call 2 ? Independent Negative Analysis

Call 1と同一のJ-Quants調査データ、`analysis_as_of`、`data_as_of`を入力する。

主として以下を分析する。

- Bear case
- Risk

**Call 1の出力をCall 2へ渡さない。**

Call 1のRecommendation、Thesis、結論、推論結果をCall 2から隔離する。

Call 2から外部Web検索や追加データ取得を行わない。

これによりCall 1とCall 2の情報条件を揃えたまま、独立したNegative Analysisを生成する。

### 10.3 Call 3 ? Synthesis

Call 3には、

- 元のJ-Quants調査データ
- `analysis_as_of`
- `data_as_of`
- Call 1の出力
- Call 2の出力

を入力する。

最低限以下を生成する。

- Contradictions
- Unresolved Questions
- Thesis
- Invalidators
- Expected Events
- Recommendation
- Confidence

Bull / Bearを単純平均して単一Scoreへ変換しない。

矛盾や未解決点は、解消されていない情報としてそのまま出力する。

### 10.4 Confidence

Confidenceは連続数値にしない。

Structured Outputsで以下のenumに限定する。

```text
low
medium
high
```

Confidenceは精密な確率を意味しない。

Allocation計算用の離散的な判断区分として使用する。

### 10.5 Structured Outputs

3回のModel CallはStructured Outputsを使用し、JSON Schemaによって出力構造を制約する。

KAIROS内部では出力をPython `dict`として扱う。

v0.1では以下を作らない。

- `models.py`
- Domain Model class階層
- Agent class
- LLM wrapper階層
- Prompt framework
- Workflow engine
- Agent Runner
- Handoff
- Model Router

必要なPrompt、JSON Schema、Responses API呼出し処理は`llm.py`にまとめる。

### 10.6 Model設定

v0.1では3 Callに同一Modelを使用する。

```text
Call 1 ─┐
Call 2 ─┼─ same model
Call 3 ─┘
```

CallごとのModel最適化やModel Routingは行わない。

Model名はConfigurationから指定可能にしてよいが、実行中に自動選択しない。

実運用後にCostまたは性能が問題になった場合のみ、CallごとのModel分離を`BACKLOG.md`で検討する。

### 10.7 Agents SDK / Jev

Agents SDKおよびJev等のDecision Modelはv0.1では使用しない。

現在のKAIROSは、

```text
Data
 ↓
Call 1 / Call 2
 ↓
Call 3
 ↓
Allocation
 ↓
Risk Check
 ↓
Report
```

という固定Python Pipelineである。

動的なTool選択、Model Routing、追加調査判断、Agent Handoff等が実際に必要になった場合だけv0.1完成後に再検討する。

### 10.8 v0.1 LLM構成

```text
OpenAI Python SDK
        ↓
Responses API
        ↓
Structured Outputs
        ↓
3 fixed Model Calls
```

KAIROS v0.1はMulti-Agent Systemとして構築しない。

**決定論的Python Pipelineの中に、情報条件を揃えながら独立性を保ったLLM推論処理を配置する。**

---

## 11. Contradiction / Thesis

Contradictionはコア機能として残す。BullとBearを平均化して単一scoreへ潰さず、矛盾と未解決点を明示する。

Thesisの最低限項目:
thesis / invalidators / expected_events

旧ARGUSのThesis state machineは実装しない。

---

## 12. Portfolio入力

portfolio.jsonはRisk / Allocation計算の入力だけに使用し、Humanが直接編集してよい。

Canonical State、Single Writer、Writer lock、Commit Envelope、Projection、Archive、Correction workflowは作らない。cashと保有銘柄・数量・評価に必要な最小項目だけ保持する。

---

## 13. Allocation

投資魅力度の判断とAllocation計算を分離する。

LLMはRecommendationとConfidenceを生成する。

Allocationの最終計算はPythonコードで行う。

Allocationを計算する対象は、

```text
BUY
ADD
```

だけとする。

以下の場合はAllocationを設定しない。

```text
WATCH
HOLD
REDUCE
SELL
REJECT
```

Confidenceは以下の離散値として扱う。

```text
low     → 0.0
medium  → 0.5
high    → 1.0
```

v0.1では単純な決定論的式を使用する。

例:

```text
allocation =
    configured_max_position
    × confidence_factor
```

`low`の場合は新規Allocationを行わない。

Risk CheckがREJECTの場合もAllocationを行わない。

複雑なPortfolio optimization、correlation model、Role Bucket、BOOTSTRAP / REPAIR modeは実装しない。

ConfidenceとAllocationの対応はPythonコード上で固定し、LLMにAllocation比率そのものを決定させない。

---

## 14. Risk Check

Risk Checkの最終判定はLLMに任せない。

Pythonの単純なrule functionとして実装する。

v0.1の最小Rule:

1. 1銘柄最大保有比率を超えない。
2. 最低現金比率を下回らない。
3. 空売りを許可しない。
4. 必須データ欠損時はBUY / ADDを許可しない。

必須データは`data.py`に単一の必須フィールド集合として定義する。

例:

```text
REQUIRED_FIELDS = [...]
```

必須項目を複数Moduleへ分散定義しない。

必須データが欠損している場合、

```text
BUY
ADD
```

についてRisk CheckをREJECTとする。

Risk CheckがREJECTの場合、

```text
suggested_allocation = none
```

とする。

WATCH、HOLD、REDUCE、SELL等の分析結果そのものを、BUY用のデータ欠損Ruleだけを理由として消さない。

Risk Check結果はv0.1では、

```text
PASS
REJECT
```

程度でよい。

巨大なPolicy / Constraint / Validator frameworkは作らない。

---

## 15. Investment Report

主要成果物はMarkdown Investment Reportとする。

Human Viewを先頭に置く。

### Human View

最低限以下を表示する。

- Recommendation
- 主要理由
- 最大の反対理由
- Confidence
- Suggested Allocation
- Risk Check結果
- Analysis as-of
- Data as-of

`Data as-of`は目立つ位置に表示する。

J-Quantsの契約Planや更新条件によって、KAIROSが使用したデータが実際の市場時点より古い可能性があるためである。

例:

```text
Recommendation: BUY
Confidence: HIGH
Suggested Allocation: 5%
Risk Check: PASS

Analysis as-of: 2026-10-05
Data as-of: 2026-10-04
```

Historical Sanity Checkでは、

```text
Analysis as-of: 2025-06-30
Data as-of: 2025-06-30以前の実使用データ基準日
```

を表示する。

### 詳細

最低限以下を含む。

- Identity
- Analysis as-of
- Data as-of
- Fundamental
- Valuation
- Bull
- Bear
- Risk
- Contradictions
- Unresolved Questions
- Thesis
- Invalidators
- Expected Events
- Recommendation
- Confidence
- Allocation
- Risk Check

ReportはHuman判断用ArtifactでありBroker commandではない。

---

## 16. Human Decision

Humanが最終投資判断を行う。KAIROSはBUY / WATCH / HOLD / ADD / REDUCE / SELL / REJECT等をRecommendationとして表示できる。

Broker操作、約定取込、Order lifecycle、reservation、Execution Fact、Compliance Record、Reconciliationは実装しない。Broker操作後にPortfolioを更新したければHumanがportfolio.jsonを直接編集する。

---

## 17. Logging

Python標準loggingを第一候補とする。

最低限:
timestamp / level / operation / target / message / exception

Secret、API key、Authorization headerを記録しない。高度なaudit pipelineやlog integrity機構は作らない。

---

## 18. Error Handling

最小分類:
Configuration Error / J-Quants・External API Error / Data Error / Model Error / Storage Error / Unexpected Error

基本動作:
ログ記録 → Human向けメッセージ → 必要なら終了。

複雑なtyped failure、retry state machine、自動Recovery、Durable Stageは作らない。Human再実行を許容する。

---

## 19. Test

KAIROS v0.1では、Softwareとして動作することと、投資判断として明らかな問題がないことを最低限確認する。

### 19.1 Software Test

優先順位:

1. stubを使ったend-to-end Vertical Slice 1本
2. `risk.py`のRule
3. J-Quants response parsing
4. 実際に発見されたbugのregression

最低限、以下がend-to-endで動作することを確認する。

```text
ticker
  ↓
J-Quants
  ↓
LLM Call 1
  ↓
LLM Call 2
  ↓
LLM Call 3
  ↓
Allocation / Risk
  ↓
Report
```

巨大test matrix、CV / RV、validation package、coverage目標のためだけのtestは作らない。

### 19.2 Historical Sanity Check

Software Test完了後、過去の実例を使ってKAIROSの判断内容を確認する。

目的は投資戦略の収益性を証明することではない。

Historical Sanity Checkでは、

```text
python main.py analyze <ticker> --as-of YYYY-MM-DD
```

を使用する。

`--as-of`指定時には、J-Quantsから取得したデータのうち指定日以前のデータだけを分析入力として使用する。

Historical Replay Framework、PIT Provider、Backtest Engineは作らない。

対象は3?10ケース程度とする。

確認対象:

- Fundamental / Valuation / Bullが重要情報を拾えているか
- 独立したBear / Riskが別の問題を発見できているか
- Call 2がCall 1の結論へ引きずられていないか
- Contradictionが意味のある対立点を抽出できているか
- Thesisが入力データと整合しているか
- Invalidatorが実用的か
- Recommendationが分析内容から大きく逸脱していないか
- Confidenceが不自然に高くないか
- Allocation / Risk Checkが意図どおり機能するか

J-Quantsの契約Planによって取得可能な過去期間が制約される場合、その範囲内のケースを使用する。

必要なケースを取得できない場合、そのケースを無理に成立させるための追加ProviderやHistorical Data基盤を作らない。

LLM自身が学習済みの未来情報を持つ可能性は排除しない。

Web検索も使用しない。

したがってHistorical Sanity Checkを、

- Backtest
- Point-in-Time完全検証
- Out-of-Sample Test
- 投資性能証明

として扱わない。

目的はKAIROSの判断ロジック上の明らかな問題を発見することである。

---

## 20. Repository構成

```text
C:\dev\kairos
├─ main.py
├─ data.py
├─ llm.py
├─ risk.py
├─ report.py
├─ .env
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
   └─ kairos_system_design_v0.1.md
```

必要がなければ空directoryやplaceholder moduleも作らない。

---

## 21. LOC制約

10,000 LOCはhard ceiling。実質目標は3,000 LOC以下。現在設計は約1,600 LOC程度で成立することを期待する。

毎日の終了時にcloc等でLOCを確認する。3,000 LOCを超えたら新機能追加を停止し、削除・単純化を確認する。10,000 LOCへ近づくこと自体を許容しない。

---

## 22. 開発順序

Day 1 — Python環境、requirements、`.env.example`、config、logging、5ファイルのskeleton。

Day 2 — stub data → stub analysis → reportまでend-to-endを通す。この時点でKAIROSというプログラム自体は動作する状態にする。

Day 3 — J-Quants取得とraw保存。

Day 4 — 3-call LLM分析。

Day 5 — Allocation、Risk Check、Report。

Day 6 — Software Test、実データ実行、bug fix。

Day 7 — Historical Sanity Check、cleanup、LOC確認、最終end-to-end実行。

Historical Sanity Checkのための専用基盤を作らない。検証環境の構築によってDay 7を超える場合は、検証機構を追加せずHumanによる手動準備・確認へ切り替える。

基盤を完全化してから価値機能へ進む方式を取らない。

---

## 23. 設計凍結とBACKLOG

本書をKAIROS v0.1 Design Baselineとして凍結する。通常の実装中に改版しない。

追加アイデア、改善案、将来機能はBACKLOG.mdへ記録して終了する。設計変更は、現在設計ではend-to-endが成立しないことが実装で判明した場合に限定する。

BACKLOG.mdはGate、承認文書、closure文書ではない。単なる将来候補メモである。

---

## 24. 成功条件

Human ticker指定
→ J-Quants取得
→ rawを外付けHDDへ保存
→ 独立Positive分析
→ 独立Bear / Risk分析
→ Contradiction統合
→ Thesis / Invalidator / Recommendation
→ 決定論的Allocation
→ 決定論的Risk Check
→ Markdown Report
→ Humanが判断可能

さらに、

- Software Testが通る
- Historical Sanity Checkを3〜10ケース程度実施する
- Historical Sanity Checkでv0.1の利用を妨げる明らかな問題が発見されていない

ことを確認する。

これをもってKAIROS v0.1の開発完了とする。

以下はv0.1完成条件ではない。

- Selection
- 自動監視
- 自動売買
- 自動Recovery
- Backtest
- PIT検証
- Paper Trading system
- 1か月Paper Trading
- Live Readiness Gate
- 投資収益性の統計的証明

---

## 25. 1-Week Virtual Trading Observation

KAIROS v0.1完成後、実際の売買を行わず、約1週間のVirtual Trading Observationを実施する。

これはv0.1の開発Gateではない。

KAIROSに追加機能を実装せず、HumanがExcelを使用して記録する。

基本フロー:

```text
KAIROS analyze
      ↓
Investment Report
      ↓
Humanが仮想売買判断
      ↓
Excelへ記録
      ↓
実際の市場価格の変化を記録
      ↓
KAIROS判断と比較
```

Excelには最低限以下を記録する。

- 判断日時
- ticker
- KAIROS Data as-of
- 判断時の実市場価格
- KAIROS Recommendation
- Confidence
- Humanの仮想判断
- 仮想数量または仮想金額
- 1日後の実市場価格
- 3日後の実市場価格
- 1週間後の実市場価格
- 騰落率
- 所感

**判断時の実市場価格とKAIROSが分析に使用した価格を同一とみなさない。**

J-QuantsのData as-ofが判断日時より古い場合、その差をExcel上で確認可能にする。

価格取得、騰落率計算、Virtual Portfolio管理をKAIROSへ実装する必要はない。

Excelによる手動記録を正式なObservation方法とする。

Observationでは主として以下を見る。

- Recommendationとその後の価格変化
- Bear / Riskが実際に有用なRiskを指摘していたか
- Bullが実際の上昇要因を捉えていたか
- KAIROSが重大な情報を見落としていなかったか
- ContradictionがHuman判断に役立ったか
- Invalidatorが実用的だったか
- Confidenceが結果に対して明らかに過大ではなかったか
- J-Quantsだけでは分析材料が不足していないか
- J-QuantsのData as-ofと実市場との時間差が実用上問題にならないか
- 3-call分析の時間・API Costが実用範囲か
- ReportがHumanの投資判断に実際に使えるか

1週間の結果を投資戦略の収益性証明とは扱わない。

Observation中に発見した改善案は原則として`BACKLOG.md`へ記録する。

重大なbugが発見された場合だけv0.1を修正する。

Observationを理由としてPaper Trading system、価格監視Job、Performance tracking機構をKAIROSへ追加しない。

---

## 26. 最終原則

KAIROS v0.1は「動く最小投資支援システム」を作る。

Simple → Working → Useful → 必要になった部分だけ強化。

機構を追加したくなった場合は、先に「その機構を削除してもKAIROSは動くか」を確認する。動くなら削除する。

Humanによる再実行、設定変更、`portfolio.json`直接編集、検証用Excelへの手入力などの手動操作を正常な運用方法として許容する。

複雑さを追加して自動化するより、Humanが理解し操作できる単純な方法をv0.1では選択する。

実装期間約1週間、3,000 LOC以下を維持する。この条件を壊す機能・工程・抽象化は削除する。
