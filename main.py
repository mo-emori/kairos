"""KAIROS command-line entry point."""

import argparse
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from data import fetch_research_data
from llm import bear_risk_analysis, positive_analysis, synthesize_analysis
from news import fetch_enabled_sources, load_sources, store_news
from report import render_report, save_report
from risk import evaluate_risk, is_held

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
PORTFOLIO_PATH = ROOT / "data" / "portfolio.json"
REPORTS_DIR = ROOT / "reports"
ENV_PATH = ROOT / ".env"


def parse_date(value: str) -> date:
    """Parse an ISO calendar date for the --as-of option."""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--as-of must be a valid date in YYYY-MM-DD format") from exc


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as json_file:
        return json.load(json_file)


def configure_logging(config: dict[str, Any]) -> None:
    level = getattr(logging, str(config.get("log_level", "INFO")).upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s operation=%(name)s %(message)s")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kairos")
    subparsers = parser.add_subparsers(dest="command", required=True)
    analyze_parser = subparsers.add_parser("analyze", help="analyze one ticker")
    analyze_parser.add_argument("ticker", help="four-digit Japanese security code")
    analyze_parser.add_argument("--as-of", type=parse_date, metavar="YYYY-MM-DD")
    subparsers.add_parser("news-update", help="retrieve enabled official RSS feeds")
    return parser


def load_data_root(path: Path = ENV_PATH) -> Path:
    """Load DATA_ROOT without requiring credentials used only by analyze."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"Configuration Error: cannot read {path.name}: {exc}") from exc
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() == "DATA_ROOT" and value.strip().strip("\"'"):
            return Path(value.strip().strip("\"'"))
    raise ValueError(f"Configuration Error: DATA_ROOT is not set in {path.name}")


def run_news_update(
    data_root: str | Path | None = None, source_path: str | Path | None = None,
    retrieved_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Fetch enabled sources and persist new URL-unique RSS records."""
    root = Path(data_root) if data_root is not None else load_data_root()
    sources = load_sources(source_path) if source_path is not None else load_sources()
    operation_time = retrieved_at or datetime.now(timezone.utc)
    results: list[dict[str, Any]] = []
    for source, records in fetch_enabled_sources(sources, operation_time):
        written = store_news(records, root)
        result = {
            "source_id": source["source_id"],
            "fetched": len(records),
            "new": len(written),
            "duplicate": len(records) - len(written),
        }
        results.append(result)
        print(
            f"source={result['source_id']} fetched={result['fetched']} "
            f"new={result['new']} duplicate={result['duplicate']}"
        )
    print(
        "total "
        f"sources={len(results)} fetched={sum(item['fetched'] for item in results)} "
        f"new={sum(item['new'] for item in results)} "
        f"duplicate={sum(item['duplicate'] for item in results)}"
    )
    return results


def run_analysis(ticker: str, as_of: date | None, model: str | None = None) -> Path:
    if len(ticker) != 4 or not ticker.isdigit():
        raise ValueError("ticker must be a four-digit security code")
    config = load_json(CONFIG_PATH)
    configured_model = model or str(config["model"])
    research_data = fetch_research_data(ticker, as_of)
    analysis_context = dict(research_data, investment_horizon=str(config["investment_horizon"]))
    portfolio = load_json(PORTFOLIO_PATH)
    held = is_held(portfolio, ticker)
    call_1 = positive_analysis(analysis_context, configured_model)
    call_2 = bear_risk_analysis(analysis_context, configured_model)
    synthesis = synthesize_analysis(analysis_context, call_1, call_2, held, configured_model)
    risk_result = evaluate_risk(
        synthesis["recommendation"], synthesis["confidence"], research_data, portfolio,
        float(config["max_position_ratio"]), float(config["min_cash_ratio"]),
    )
    markdown = render_report(analysis_context, call_1, call_2, synthesis, risk_result, held)
    return save_report(markdown, ticker, research_data["analysis_as_of"], REPORTS_DIR)


def main() -> int:
    args = build_parser().parse_args()
    config = load_json(CONFIG_PATH)
    configure_logging(config)
    if args.command == "analyze":
        try:
            report_path = run_analysis(args.ticker, args.as_of, str(config["model"]))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logging.getLogger("analyze").error("target=%s message=%s", args.ticker, exc)
            return 1
        print(f"Analysis complete: {report_path}")
    elif args.command == "news-update":
        try:
            run_news_update()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logging.getLogger("news-update").error("target=feeds message=%s", exc)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
