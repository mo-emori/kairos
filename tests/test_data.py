import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import data


class JQuantsParsingTest(unittest.TestCase):
    def test_actual_shaped_master_fixture_produces_compact_identity(self):
        raw = {"endpoint": data.MASTER_PATH, "pages": [{"data": [{
            "Date": "2025-06-30", "Code": "72030", "CoName": "トヨタ自動車",
            "CoNameEn": "TOYOTA MOTOR CORPORATION", "S17": "3",
            "S17Nm": "自動車・輸送機", "S33": "3700", "S33Nm": "輸送用機器",
            "ScaleCat": "TOPIX Core30", "Mkt": "0111", "MktNm": "プライム",
        }]}]}
        self.assertEqual(data.shape_company_identity(raw, "7203", date(2025, 6, 30)), {
            "as_of": "2025-06-30", "code": "72030", "name_ja": "トヨタ自動車",
            "name_en": "TOYOTA MOTOR CORPORATION", "industry_code": "3700",
            "industry_name": "輸送用機器",
        })
        self.assertIsNone(data.shape_company_identity(raw, "7203", date(2025, 6, 29)))

    def test_as_of_filters_by_market_and_disclosure_dates_and_uses_selected_records(self):
        prices = {"endpoint": data.PRICE_PATH, "pages": [{"data": [
            {"Date": "2025-06-29", "AdjC": "2500"},
            {"Date": "2025-07-01", "AdjC": "9999"},
        ]}]}
        financials = {"endpoint": data.FINANCIAL_PATH, "pages": [{"data": [
            {"DiscDate": "2025-06-28", "CurFYEn": "2025-03-31", "Sales": "1000",
             "OP": "100", "NP": "70", "EPS": "100", "EqAR": "40"},
            {"DiscDate": "2025-07-02", "CurFYEn": "2024-03-31", "Sales": "9999",
             "OP": "999", "NP": "999", "EPS": "1", "EqAR": "1"},
        ]}]}
        calls = []

        identity = {"endpoint": data.MASTER_PATH, "pages": [{"data": [{
            "Date": "2025-06-30", "Code": "72030", "CoName": "トヨタ自動車",
            "CoNameEn": "TOYOTA MOTOR CORPORATION", "S33": "3700", "S33Nm": "輸送用機器",
        }]}]}

        def fake_request(path, code, api_key, as_of=None):
            calls.append((path, code, api_key, as_of))
            return {data.PRICE_PATH: prices, data.FINANCIAL_PATH: financials,
                    data.MASTER_PATH: identity}[path]

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(data, "_load_env", return_value={"JQUANTS_API_KEY": "local", "DATA_ROOT": directory}), \
             patch.object(data, "_request_all", side_effect=fake_request):
            result = data.fetch_research_data("7203", date(2025, 6, 30))
            archived = list(Path(directory).rglob("*.json"))

        self.assertEqual([call[1] for call in calls], ["72030", "72030", "72030"])
        self.assertEqual(calls[-1][3], date(2025, 6, 30))
        self.assertEqual(result["price"], 2500)
        self.assertEqual(result["revenue"], 1000)
        self.assertEqual(result["financial_disclosure_date"], "2025-06-28")
        self.assertEqual(result["data_as_of"], "2025-06-29")
        self.assertEqual(result["metadata"], {
            "source": "J-Quants API V2", "ticker": "7203",
            "analysis_as_of": "2025-06-30", "data_as_of": "2025-06-29",
        })
        self.assertIsNone(result["market"])
        self.assertIsNone(result["sector"])
        self.assertEqual(result["company_name"], "トヨタ自動車")
        self.assertEqual(result["company_identity"]["industry_name"], "輸送用機器")
        self.assertEqual(len(archived), 3)

    def test_data_as_of_ignores_newer_unusable_records(self):
        prices = {"endpoint": data.PRICE_PATH, "pages": [{"data": [
            {"Date": "2025-06-29", "AdjC": "2500"}, {"Date": "2025-06-30", "AdjC": ""},
        ]}]}
        financials = {"endpoint": data.FINANCIAL_PATH, "pages": [{"data": [
            {"DiscDate": "2025-06-28", "Sales": "1000", "OP": "100", "NP": "70",
             "EPS": "100", "EqAR": "40"},
            {"DiscDate": "2025-06-30", "Sales": "", "OP": "", "NP": "", "EPS": "", "EqAR": ""},
        ]}]}

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(data, "_load_env", return_value={"JQUANTS_API_KEY": "local", "DATA_ROOT": directory}), \
             patch.object(data, "_request_all", side_effect=[
                 prices, financials, {"endpoint": data.MASTER_PATH, "pages": [{"data": []}]},
             ]):
            result = data.fetch_research_data("7203")

        self.assertEqual(result["price_date"], "2025-06-29")
        self.assertEqual(result["financial_disclosure_date"], "2025-06-28")
        self.assertEqual(result["data_as_of"], "2025-06-29")

    def test_same_period_prior_year_matching_rejects_previous_mismatched_period(self):
        current = {"CurPerType": "2Q", "CurFYEn": "2026-03-31"}
        records = [
            {"CurPerType": "1Q", "CurFYEn": "2026-03-31", "DiscDate": "2025-08-01"},
            {"CurPerType": "2Q", "CurFYEn": "2025-03-31", "DiscDate": "2024-11-01", "Sales": "80"},
            {"CurPerType": "1Q", "CurFYEn": "2025-03-31", "DiscDate": "2024-08-01", "Sales": "70"},
        ]
        self.assertEqual(data._prior_comparable(current, records)["Sales"], "80")

    def test_change_pct_is_null_for_nonpositive_prior_and_empty_is_none(self):
        self.assertIsNone(data._metric(10, 0)["change_pct"])
        self.assertIsNone(data._metric(10, -2)["change_pct"])
        self.assertIsNone(data._number(""))

    def test_cash_flow_comparison_requires_period_coverage(self):
        compatible = data._cash_flow({"CurPerSt": "2025-04-01", "CurPerEn": "2025-09-30",
                                      "CFO": "120", "NP": "100"})
        incompatible = data._cash_flow({"CFO": "120", "NP": "100"})
        self.assertEqual(compatible["operating_cash_flow_minus_net_income"], 20)
        self.assertIsNone(incompatible["operating_cash_flow_minus_net_income"])

    def test_forecast_uses_current_fy_for_interim_and_next_fy_for_fy(self):
        interim = data._forecast({"CurPerType": "2Q", "CurFYSt": "2025-04-01", "CurFYEn": "2026-03-31",
                                  "FSales": "100", "FEPS": "5", "NxFSales": "999"}, 50)
        full_year = data._forecast({"CurPerType": "FY", "CurFYSt": "2024-04-01", "CurFYEn": "2025-03-31",
                                   "NxtFYSt": "2025-04-01", "NxtFYEn": "2026-03-31",
                                   "FSales": "100", "NxFSales": "200", "NxFEPS": "10"}, 50)
        self.assertEqual((interim["revenue"], interim["period_end"]), (100, "2026-03-31"))
        self.assertEqual((full_year["revenue"], full_year["forward_per"]), (200, 5))
        later_without_forecast = {"CurPerType": "2Q", "CurFYSt": "2025-04-01",
                                  "CurFYEn": "2026-03-31", "DiscDate": "2025-11-01"}
        selected = data._latest_relevant_forecast(later_without_forecast, [
            {"CurPerType": "1Q", "CurFYSt": "2025-04-01", "CurFYEn": "2026-03-31",
             "DiscDate": "2025-08-01", "FSales": "150"}, later_without_forecast,
        ], 50)
        self.assertEqual(selected["revenue"], 150)

    def test_price_returns_use_adjusted_close_cutoff_windows_and_insufficient_null(self):
        records = [{"Date": f"2025-01-{index:03d}", "AdjC": index + 1, "C": 99999}
                   for index in range(253)]
        trend = data._price_trend(records)
        self.assertAlmostEqual(trend["returns"]["21_observations"], 253 / 232 - 1)
        self.assertAlmostEqual(trend["returns"]["63_observations"], 253 / 190 - 1)
        self.assertAlmostEqual(trend["returns"]["126_observations"], 253 / 127 - 1)
        self.assertAlmostEqual(trend["returns"]["252_observations"], 252)
        self.assertIsNone(data._price_trend(records[:21])["returns"]["21_observations"])

    def test_required_fields_remain_v01(self):
        self.assertEqual(data.REQUIRED_FIELDS, (
            "ticker", "analysis_as_of", "data_as_of", "price", "revenue",
            "operating_profit", "net_income", "equity_ratio", "per",
        ))


if __name__ == "__main__":
    unittest.main()
