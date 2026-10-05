"""UTF-8 Markdown investment report generation."""

from pathlib import Path
from typing import Any


def _bullets(values: list[str]) -> str:
    return "\n".join(f"- {value}" for value in values)


def _price(value: Any) -> str:
    return "Unavailable" if value is None else f"{value:,.2f}"


def _value(value: Any) -> str:
    return "Unavailable" if value is None else f"{value:,.2f}"


def _percent(value: Any) -> str:
    return "Unavailable" if value is None else f"{value:.2%}"


def _company_context(company: dict[str, Any] | None) -> str:
    if not company:
        return "Unavailable"
    historical = company.get("historical_comparable") or {}
    metrics = historical.get("metrics") or {}
    rows = ["| Metric | Current | Prior comparable | Change | Change % |",
            "|---|---:|---:|---:|---:|"]
    for name, values in metrics.items():
        display = _percent if name in {"operating_margin", "net_margin", "equity_ratio"} else _value
        rows.append(f"| {name} | {display(values.get('current'))} | {display(values.get('prior_comparable'))} | "
                    f"{display(values.get('change'))} | {_percent(values.get('change_pct'))} |")
    cash, forecast, trend = company.get("cash_flow") or {}, company.get("forecast") or {}, company.get("price_trend") or {}
    returns = trend.get("returns") or {}
    return "\n".join([
        f"Period: {historical.get('period_type') or 'Unavailable'} "
        f"({historical.get('period_start') or 'Unavailable'} to {historical.get('period_end') or 'Unavailable'}); "
        f"prior {historical.get('prior_period_start') or 'Unavailable'} to {historical.get('prior_period_end') or 'Unavailable'}",
        "", *rows, "", "### Cash Flow",
        f"- Operating CF: {_value(cash.get('operating_cash_flow'))}",
        f"- Investing CF: {_value(cash.get('investing_cash_flow'))}",
        f"- Financing CF: {_value(cash.get('financing_cash_flow'))}",
        f"- Cash and cash equivalents: {_value(cash.get('cash_and_cash_equivalents'))}",
        f"- Operating CF minus period-compatible net income: {_value(cash.get('operating_cash_flow_minus_net_income'))}",
        "", "### Company Forecast",
        f"- Period: {forecast.get('period_start') or 'Unavailable'} to {forecast.get('period_end') or 'Unavailable'}",
        f"- Revenue / OP / NP: {_value(forecast.get('revenue'))} / {_value(forecast.get('operating_profit'))} / {_value(forecast.get('net_income'))}",
        f"- EPS / dividend / forward PER: {_value(forecast.get('eps'))} / {_value(forecast.get('dividend_per_share'))} / {_value(forecast.get('forward_per'))}",
        "", "### Price Trend (Adjusted Close)",
        f"- As-of adjusted close: {_value(trend.get('adjusted_close'))} ({trend.get('price_date') or 'Unavailable'})",
        f"- 21 / 63 / 126 / 252 observation returns: {_percent(returns.get('21_observations'))} / "
        f"{_percent(returns.get('63_observations'))} / {_percent(returns.get('126_observations'))} / {_percent(returns.get('252_observations'))}",
        f"- Latest full-year ROE: {_percent((company.get('roe') or {}).get('value'))}",
    ])


def _baseline_context(context: dict[str, Any] | None) -> str:
    if not context:
        return "Unavailable"
    trend = context.get("trend") or {}
    returns = trend.get("returns") or {}
    relative = context.get("relative_performance") or {}
    return "\n".join([
        f"- Baseline: {context.get('name') or 'Unavailable'}",
        f"- As-of value: {_value(trend.get('value'))} ({trend.get('date') or 'Unavailable'})",
        f"- 21 / 63 / 126 / 252 observation returns: {_percent(returns.get('21_observations'))} / "
        f"{_percent(returns.get('63_observations'))} / {_percent(returns.get('126_observations'))} / "
        f"{_percent(returns.get('252_observations'))}",
        f"- Relative performance: "
        f"{', '.join(f'{key}={_percent(value)}' for key, value in relative.items()) or 'Unavailable'}",
    ])


def render_report(
    research_data: dict[str, Any],
    call_1: dict[str, Any],
    call_2: dict[str, Any],
    synthesis: dict[str, Any],
    risk_result: dict[str, Any],
    held: bool,
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
- **Investment horizon:** {research_data['investment_horizon']}
- **Holding state:** {'Held' if held else 'Not held'}

## Identity

- Ticker: {research_data['ticker']}
- Company: {research_data['company_name']}
- Source: {research_data['source']}
- Price: {_price(research_data['price'])}

## Analysis as-of

{research_data['analysis_as_of']}

## Data as-of

{research_data['data_as_of']}

## Market Context

{_baseline_context(research_data.get('market'))}

## Sector Context

{_baseline_context(research_data.get('sector'))}

## Company Context

{_company_context(research_data.get('company'))}

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
