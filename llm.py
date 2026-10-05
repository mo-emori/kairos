"""Three deterministic analysis calls for the KAIROS stub vertical slice."""

from typing import Any


def positive_analysis(research_data: dict[str, Any]) -> dict[str, Any]:
    """Stub Call 1: fundamental, valuation, and bull analysis."""
    return {
        "call": "Call 1 - Positive Analysis",
        "fundamental": "Revenue and operating profit are substantial, with positive net income.",
        "valuation": "P/E is unavailable." if research_data["per"] is None else f"The observed P/E is {research_data['per']:.1f}x.",
        "bull_case": "Earnings scale and a sound equity base could support durable value creation.",
        "evidence": ["reported operating profit", "reported net income", "observed price and EPS"],
    }


def bear_risk_analysis(research_data: dict[str, Any]) -> dict[str, Any]:
    """Stub Call 2: independently assess bear factors using only base data."""
    return {
        "call": "Call 2 - Independent Bear/Risk Analysis",
        "bear_case": "Large absolute earnings do not show whether growth is sustainable.",
        "risks": [
            "The compact research data omits cash-flow and debt detail.",
            "Equity ratio is unavailable." if research_data["equity_ratio"] is None else f"An equity ratio of {research_data['equity_ratio']:.0%} leaves balance-sheet uncertainty.",
            "A single price and valuation snapshot cannot show market-cycle sensitivity.",
        ],
        "evidence": ["limited research fields", "no trend analysis", "no cash-flow data"],
    }


def synthesize_analysis(
    research_data: dict[str, Any],
    call_1: dict[str, Any],
    call_2: dict[str, Any],
) -> dict[str, Any]:
    """Stub Call 3: synthesize base data and both independent analyses."""
    return {
        "call": "Call 3 - Synthesis",
        "contradictions": [
            "Strong reported earnings support the bull case, but this analysis does not test their durability."
        ],
        "unresolved_questions": [
            "How much of earnings converts to free cash flow?",
            "How sensitive are earnings to currency and the economic cycle?",
        ],
        "thesis": "Moderate valuation and positive earnings justify a small starter position, subject to missing detail.",
        "invalidators": [
            "Operating profit turns negative.",
            "Material leverage is discovered when complete data becomes available.",
        ],
        "expected_events": ["Next financial-results update", "Next J-Quants data update"],
        "recommendation": "BUY",
        "confidence": "medium",
        "primary_reason": call_1["bull_case"],
        "strongest_counterargument": call_2["bear_case"],
        "base_data_identity": f"{research_data['ticker']} as of {research_data['data_as_of']}",
    }
