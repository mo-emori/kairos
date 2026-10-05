"""Minimal deterministic allocation and risk behavior."""

from typing import Any

from data import REQUIRED_FIELDS

CONFIDENCE_FACTOR = {"low": 0.0, "medium": 0.5, "high": 1.0}
EPSILON = 1e-12


def _position_ratio(portfolio: dict[str, Any], ticker: str) -> float:
    """Read the target's current ratio from the human-maintained portfolio."""
    for holding in portfolio.get("holdings", []):
        if str(holding.get("ticker")) == ticker:
            return float(holding.get("position_ratio", 0.0))
    return 0.0


def is_held(portfolio: dict[str, Any], ticker: str) -> bool:
    """Return the minimal holding fact used by recommendation synthesis."""
    return _position_ratio(portfolio, ticker) > 0


def evaluate_risk(
    recommendation: str,
    confidence: str,
    research_data: dict[str, Any],
    portfolio: dict[str, Any],
    max_position: float,
    min_cash_ratio: float,
) -> dict[str, Any]:
    """Calculate allocation and apply the frozen design's simple risk rules."""
    action = recommendation.upper()
    missing = [field for field in REQUIRED_FIELDS if research_data.get(field) is None]
    if action not in {"BUY", "ADD"}:
        return {"status": "PASS", "reason": "Allocation applies only to BUY or ADD.", "suggested_allocation": None}
    if missing:
        return {"status": "REJECT", "reason": f"Missing required data: {', '.join(missing)}", "suggested_allocation": None}
    cash = float(portfolio.get("cash", 0.0))
    cash_ratio = float(portfolio.get("cash_ratio", 0.0))
    current_position_ratio = _position_ratio(portfolio, str(research_data["ticker"]))
    has_short_position = any(float(holding.get("position_ratio", 0.0)) < 0 for holding in portfolio.get("holdings", []))
    if cash < 0 or cash_ratio < 0 or has_short_position:
        return {"status": "REJECT", "reason": "Negative portfolio values would imply short selling.", "suggested_allocation": None}
    if cash == 0 or cash_ratio == 0:
        return {"status": "REJECT", "reason": "No cash is available; short selling is not allowed.", "suggested_allocation": None}
    base_allocation = max_position * CONFIDENCE_FACTOR.get(confidence.lower(), 0.0)
    if base_allocation <= 0:
        return {"status": "PASS", "reason": "Low or unknown confidence produces no allocation.", "suggested_allocation": None}
    remaining_room = max(0.0, max_position - current_position_ratio)
    allocation = min(base_allocation, remaining_room) if action == "ADD" else base_allocation
    if allocation <= EPSILON:
        return {"status": "REJECT", "reason": "No room remains under the single-position maximum.", "suggested_allocation": None}
    if current_position_ratio + allocation > max_position + EPSILON:
        return {"status": "REJECT", "reason": "Allocation would exceed the single-position maximum.", "suggested_allocation": None}
    if cash_ratio - allocation < min_cash_ratio - EPSILON:
        return {"status": "REJECT", "reason": "Allocation would breach the minimum cash ratio.", "suggested_allocation": None}
    portfolio_value = cash / cash_ratio
    return {
        "status": "PASS",
        "reason": "Required data, maximum-position, cash, and no-short checks passed.",
        "suggested_allocation": allocation,
        "suggested_amount": round(portfolio_value * allocation, 2),
    }
