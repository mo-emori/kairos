"""KAIROS command-line entry point."""

import argparse
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from data import fetch_research_data
from llm import bear_risk_analysis, positive_analysis, synthesize_analysis
from report import render_report, save_report
from risk import evaluate_risk

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
PORTFOLIO_PATH = ROOT / "data" / "portfolio.json"
REPORTS_DIR = ROOT / "reports"


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
    return parser


def run_analysis(ticker: str, as_of: date | None) -> Path:
    if len(ticker) != 4 or not ticker.isdigit():
        raise ValueError("ticker must be a four-digit security code")
    research_data = fetch_research_data(ticker, as_of)
    call_1 = positive_analysis(research_data)
    call_2 = bear_risk_analysis(research_data)
    synthesis = synthesize_analysis(research_data, call_1, call_2)
    risk_result = evaluate_risk(
        synthesis["recommendation"], synthesis["confidence"], research_data, load_json(PORTFOLIO_PATH)
    )
    markdown = render_report(research_data, call_1, call_2, synthesis, risk_result)
    return save_report(markdown, ticker, research_data["analysis_as_of"], REPORTS_DIR)


def main() -> int:
    args = build_parser().parse_args()
    configure_logging(load_json(CONFIG_PATH))
    if args.command == "analyze":
        try:
            report_path = run_analysis(args.ticker, args.as_of)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logging.getLogger("analyze").error("target=%s message=%s", args.ticker, exc)
            return 1
        print(f"Analysis complete: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
