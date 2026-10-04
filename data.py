"""Deterministic research data for the KAIROS stub vertical slice."""

from datetime import date
from typing import Any

REQUIRED_FIELDS: tuple[str, ...] = (
    "ticker", "company_name", "analysis_as_of", "data_as_of", "price",
    "revenue", "operating_profit", "net_income", "equity_ratio", "per",
)
STUB_LATEST_DATE = date(2026, 10, 5)


def fetch_research_data(ticker: str, as_of: date | None = None) -> dict[str, Any]:
    """Return a small, local data set shaped like future J-Quants input."""
    analysis_date = as_of or STUB_LATEST_DATE
    return {
        "source": "deterministic local stub (J-Quants-shaped)",
        "ticker": ticker,
        "company_name": "Toyota Motor Corporation" if ticker == "7203" else f"Stub Company {ticker}",
        "analysis_as_of": analysis_date.isoformat(),
        "data_as_of": analysis_date.isoformat(),
        "price": 2_750.0,
        "revenue": 48_000_000_000_000,
        "operating_profit": 5_200_000_000_000,
        "net_income": 4_100_000_000_000,
        "equity_ratio": 0.38,
        "per": 10.5,
    }
