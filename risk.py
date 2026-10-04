"""Minimal deterministic allocation and risk behavior for stub execution."""

from typing import Any

from data import REQUIRED_FIELDS

MAX_POSITION = 0.10
MIN_CASH_RATIO = 0.20
CONFIDENCE_FACTOR = {"low": 0.0, "medium": 0.5, "high": 1.0}


def evaluate_risk(
    recommendation: str,
    confidence: str,
    research_data: dict[str, Any],
    portfolio: dict[str, Any],
) -> dict[str, Any]:
    """Apply just enough deterministic policy to exercise the designed path."""
    action = recommendation.upper()
    missing = [field for field in REQUIRED_FIELDS if research_data.get(field) is None]
    if action not in {"BUY", "ADD"}:
        return {"status": "PASS", "reason": "Allocation applies only to BUY or ADD.", "suggested_allocation": None}
    if missing:
        return {"status": "REJECT", "reason": f"Missing required data: {', '.join(missing)}", "suggested_allocation": None}
    cash = float(portfolio.get("cash", 0))
    if cash <= 0:
        return {"status": "REJECT", "reason": "No cash is available; short selling is not allowed.", "suggested_allocation": None}
    allocation = MAX_POSITION * CONFIDENCE_FACTOR.get(confidence.lower(), 0.0)
    if allocation <= 0:
        return {"status": "PASS", "reason": "Low or unknown confidence produces no allocation.", "suggested_allocation": None}
    if 1.0 - allocation < MIN_CASH_RATIO:
        return {"status": "REJECT", "reason": "Allocation would breach the minimum cash ratio.", "suggested_allocation": None}
    return {
        "status": "PASS",
        "reason": "Required data, maximum-position, cash, and no-short checks passed.",
        "suggested_allocation": allocation,
        "suggested_amount": round(cash * allocation, 2),
    }
