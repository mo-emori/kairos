import json
import io
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import main


class VerticalSliceTest(unittest.TestCase):
    def test_news_enrich_cli_orchestration_with_mocked_fetch_and_extract(self):
        record = {"source": "Fixture", "published_at": "2026-10-06T00:00:00+00:00",
                  "retrieved_at": "2026-10-07T00:00:00+00:00", "title": "Update",
                  "summary": "", "url": "https://example.test/article"}
        with tempfile.TemporaryDirectory() as directory:
            news_root = Path(directory) / "news" / "raw"
            news_root.mkdir(parents=True)
            (news_root / "2026-10-07.jsonl").write_text(
                json.dumps(record) + "\n", encoding="utf-8")
            with patch("news.fetch_url", return_value="<article>body</article>"), \
                 patch("news.extract", return_value="Extracted article text " * 4), \
                 patch("sys.stdout", new_callable=io.StringIO) as output:
                result = main.run_news_enrich(directory)
        self.assertEqual(result, {"processed": 1, "success": 1,
                                  "already_enriched": 0, "failed": 0})
        self.assertIn("processed=1 success=1 already_enriched=0 failed=0", output.getvalue())

    def test_news_update_cli_orchestration_and_duplicate_counts(self):
        source = {"source_id": "official", "name": "Official",
                  "url": "https://example.test/feed.xml", "default_layer": "market",
                  "enabled": True}
        record = {"source": "Official", "published_at": "2026-10-06T00:00:00+00:00",
                  "retrieved_at": "2026-10-07T00:00:00+00:00", "title": "Update",
                  "summary": "Summary", "url": "https://example.test/item"}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(main, "load_sources", return_value=[source]), \
             patch.object(main, "fetch_enabled_sources", return_value=[(source, [record])]), \
             patch("sys.stdout", new_callable=io.StringIO) as output:
            first = main.run_news_update(
                directory, retrieved_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
            )
            second = main.run_news_update(
                directory, retrieved_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
            )
        self.assertEqual(first[0], {"source_id": "official", "fetched": 1,
                                    "new": 1, "duplicate": 0})
        self.assertEqual(second[0], {"source_id": "official", "fetched": 1,
                                     "new": 0, "duplicate": 1})
        self.assertIn("total sources=1 fetched=1 new=0 duplicate=1", output.getvalue())

    def test_news_update_main_returns_failure_for_identified_source(self):
        with patch("sys.argv", ["main.py", "news-update"]), \
             patch.object(main, "load_json", return_value={"log_level": "INFO"}), \
             patch.object(main, "run_news_update",
                          side_effect=ValueError("News Feed Error: source=broken: offline")):
            self.assertEqual(main.main(), 1)

    def test_analysis_pipeline_writes_utf8_markdown_and_keeps_call_2_independent(self):
        research = {
            "source": "local fixture", "ticker": "7203", "company_name": "トヨタ自動車",
            "analysis_as_of": "2026-10-05", "data_as_of": "2026-10-02",
            "price": 3000, "revenue": 100000, "operating_profit": 10000,
            "net_income": 7000, "equity_ratio": 40, "per": 12,
            "market": None, "sector": None,
            "company": {"historical_comparable": {"period_type": "FY", "period_start": "2025-04-01",
                "period_end": "2026-03-31", "prior_period_start": None, "prior_period_end": None,
                "metrics": {"revenue": {"current": 100000, "prior_comparable": None,
                "change": None, "change_pct": None}}}, "cash_flow": None, "forecast": None,
                "price_trend": {"price_date": "2026-10-02", "adjusted_close": 3000, "returns": {}},
                "roe": None},
        }
        call_1 = {"fundamental": "収益は安定", "valuation": "適正", "bull_case": "成長余地", "evidence": ["売上"]}
        call_2 = {"bear_case": "為替リスク", "risks": ["需要減"], "evidence": ["開示情報"]}
        synthesis = {
            "recommendation": "BUY", "confidence": "medium", "primary_reason": "収益力",
            "strongest_counterargument": "為替", "contradictions": ["成長と需要"],
            "unresolved_questions": ["次期需要"], "thesis": "中長期成長",
            "invalidators": ["利益急減"], "expected_events": ["決算"],
        }
        portfolio = {"cash": 500000, "cash_ratio": 0.5, "holdings": []}
        seen = {}

        def fake_positive(data, model):
            seen["positive"] = (data, model)
            return call_1

        def fake_bear(data, model):
            seen["bear"] = (data, model)
            return call_2

        def fake_synthesis(data, positive, bear, held, model):
            seen["synthesis"] = (data, positive, bear, held, model)
            return synthesis

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            portfolio_path = root / "portfolio.json"
            config_path.write_text(json.dumps({"model": "local-model", "investment_horizon": "3 months",
                                               "max_position_ratio": 0.1,
                                               "min_cash_ratio": 0.2}), encoding="utf-8")
            portfolio_path.write_text(json.dumps(portfolio), encoding="utf-8")
            with patch.multiple(main, CONFIG_PATH=config_path, PORTFOLIO_PATH=portfolio_path,
                                REPORTS_DIR=root / "reports"), \
                 patch.object(main, "fetch_research_data", return_value=research), \
                 patch.object(main, "positive_analysis", side_effect=fake_positive), \
                 patch.object(main, "bear_risk_analysis", side_effect=fake_bear), \
                 patch.object(main, "synthesize_analysis", side_effect=fake_synthesis):
                report_path = main.run_analysis("7203", date(2026, 10, 5))

            markdown = report_path.read_text(encoding="utf-8")

        expected_context = dict(research, investment_horizon="3 months")
        self.assertEqual(seen["positive"], (expected_context, "local-model"))
        self.assertEqual(seen["bear"], (expected_context, "local-model"))
        self.assertNotIn("holding_status", seen["positive"][0])
        self.assertNotIn("portfolio", seen["positive"][0])
        self.assertNotIn("holding_status", seen["bear"][0])
        self.assertNotIn("portfolio", seen["bear"][0])
        self.assertNotIn(call_1, seen["bear"])
        self.assertEqual(seen["synthesis"], (expected_context, call_1, call_2, False, "local-model"))
        for heading in ("## Human View", "### Fundamental", "### Valuation", "### Bull",
                        "### Bear", "### Risk", "### Contradictions", "### Thesis",
                        "## Market Context", "## Sector Context", "## Company Context",
                        "### Cash Flow", "### Company Forecast",
                        "### Price Trend (Adjusted Close)", "## Allocation", "## Risk Check"):
            self.assertIn(heading, markdown)
        self.assertIn("トヨタ自動車", markdown)
        self.assertIn("Suggested allocation:** 5.0%", markdown)
        self.assertIn("Investment horizon:** 3 months", markdown)
        self.assertIn("Holding state:** Not held", markdown)
        self.assertIn("Unavailable", markdown)
        self.assertIn("## Market Context\n\nUnavailable", markdown)
        self.assertIn("## Sector Context\n\nUnavailable", markdown)


if __name__ == "__main__":
    unittest.main()
