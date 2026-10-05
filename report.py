"""UTF-8 Markdown investment report generation."""

from pathlib import Path
from typing import Any


def _bullets(values: list[str]) -> str:
    return "\n".join(f"- {value}" for value in values)


def _price(value: Any) -> str:
    return "Unavailable" if value is None else f"{value:,.2f}"


def render_report(
    research_data: dict[str, Any],
    call_1: dict[str, Any],
    call_2: dict[str, Any],
    synthesis: dict[str, Any],
    risk_result: dict[str, Any],
) -> str:
    """Render Human View first, followed by evidence from the full pipeline."""
    allocation = risk_result["suggested_allocation"]
    allocation_text = "None (not applicable)" if allocation is None else f"{allocation:.1%}"
    amount = risk_result.get("suggested_amount")
    amount_text = "None (not applicable)" if amount is None else f"{amount:,.0f}"
    return f"""# KAIROS Investment Report — {research_data['ticker']}

## Human View

- **Recommendation:** {synthesis['recommendation']}
- **Primary reason:** {synthesis['primary_reason']}
- **Strongest opposing reason:** {call_2['bear_case']}
- **Confidence:** {synthesis['confidence'].upper()}
- **Suggested allocation:** {allocation_text} (amount: {amount_text})
- **Risk Check:** {risk_result['status']} — {risk_result['reason']}
- **Analysis as-of:** {research_data['analysis_as_of']}
- **Data as-of:** {research_data['data_as_of']}

## Identity

- Ticker: {research_data['ticker']}
- Company: {research_data['company_name']}
- Source: {research_data['source']}
- Price: {_price(research_data['price'])}

## Analysis as-of

{research_data['analysis_as_of']}

## Data as-of

{research_data['data_as_of']}

## Call 1 — Positive Analysis

### Fundamental

{call_1['fundamental']}

### Valuation

{call_1['valuation']}

### Bull

{call_1['bull_case']}

Evidence:
{_bullets(call_1['evidence'])}

## Call 2 — Independent Bear/Risk Analysis

### Bear

{call_2['bear_case']}

### Risk

{_bullets(call_2['risks'])}

Evidence:
{_bullets(call_2['evidence'])}

## Call 3 — Synthesis

### Contradictions

{_bullets(synthesis['contradictions'])}

### Unresolved Questions

{_bullets(synthesis['unresolved_questions'])}

### Thesis

{synthesis['thesis']}

### Invalidators

{_bullets(synthesis['invalidators'])}

### Expected Events

{_bullets(synthesis['expected_events'])}

### Recommendation

{synthesis['recommendation']}

### Confidence

{synthesis['confidence'].upper()}

## Allocation

- Suggested allocation: {allocation_text}
- Suggested amount: {amount_text}

## Risk Check

- Status: {risk_result['status']}
- Reason: {risk_result['reason']}

This report is decision support only. The human makes the final investment and broker decision.
"""


def save_report(markdown: str, ticker: str, analysis_as_of: str, reports_dir: Path) -> Path:
    """Write one deterministic report path using explicit UTF-8 encoding."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{ticker}_{analysis_as_of}.md"
    path.write_text(markdown, encoding="utf-8")
    return path
