import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import main


class VerticalSliceTest(unittest.TestCase):
    def test_analysis_pipeline_writes_utf8_markdown_and_keeps_call_2_independent(self):
        research = {
            "source": "local fixture", "ticker": "7203", "company_name": "トヨタ自動車",
            "analysis_as_of": "2026-10-05", "data_as_of": "2026-10-02",
            "price": 3000, "revenue": 100000, "operating_profit": 10000,
            "net_income": 7000, "equity_ratio": 40, "per": 12,
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

        def fake_synthesis(data, positive, bear, model):
            seen["synthesis"] = (data, positive, bear, model)
            return synthesis

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            portfolio_path = root / "portfolio.json"
            config_path.write_text(json.dumps({"model": "local-model", "max_position_ratio": 0.1,
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

        self.assertEqual(seen["positive"], (research, "local-model"))
        self.assertEqual(seen["bear"], (research, "local-model"))
        self.assertNotIn(call_1, seen["bear"])
        self.assertEqual(seen["synthesis"], (research, call_1, call_2, "local-model"))
        for heading in ("## Human View", "### Fundamental", "### Valuation", "### Bull",
                        "### Bear", "### Risk", "### Contradictions", "### Thesis",
                        "## Allocation", "## Risk Check"):
            self.assertIn(heading, markdown)
        self.assertIn("トヨタ自動車", markdown)
        self.assertIn("Suggested allocation:** 5.0%", markdown)


if __name__ == "__main__":
    unittest.main()
