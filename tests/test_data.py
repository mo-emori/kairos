import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import data


class JQuantsParsingTest(unittest.TestCase):
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

        def fake_request(path, code, api_key):
            calls.append((path, code, api_key))
            return prices if path == data.PRICE_PATH else financials

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(data, "_load_env", return_value={"JQUANTS_API_KEY": "local", "DATA_ROOT": directory}), \
             patch.object(data, "_request_all", side_effect=fake_request):
            result = data.fetch_research_data("7203", date(2025, 6, 30))
            archived = list(Path(directory).rglob("*.json"))

        self.assertEqual([call[1] for call in calls], ["72030", "72030"])
        self.assertEqual(result["price"], 2500)
        self.assertEqual(result["revenue"], 1000)
        self.assertEqual(result["financial_disclosure_date"], "2025-06-28")
        self.assertEqual(result["data_as_of"], "2025-06-29")
        self.assertEqual(len(archived), 2)

    def test_data_as_of_ignores_newer_unusable_records(self):
        prices = {"endpoint": data.PRICE_PATH, "pages": [{"data": [
            {"Date": "2025-06-29", "C": "2500"}, {"Date": "2025-06-30", "C": ""},
        ]}]}
        financials = {"endpoint": data.FINANCIAL_PATH, "pages": [{"data": [
            {"DiscDate": "2025-06-28", "Sales": "1000", "OP": "100", "NP": "70",
             "EPS": "100", "EqAR": "40"},
            {"DiscDate": "2025-06-30", "Sales": "", "OP": "", "NP": "", "EPS": "", "EqAR": ""},
        ]}]}

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(data, "_load_env", return_value={"JQUANTS_API_KEY": "local", "DATA_ROOT": directory}), \
             patch.object(data, "_request_all", side_effect=[prices, financials]):
            result = data.fetch_research_data("7203")

        self.assertEqual(result["price_date"], "2025-06-29")
        self.assertEqual(result["financial_disclosure_date"], "2025-06-28")
        self.assertEqual(result["data_as_of"], "2025-06-29")


if __name__ == "__main__":
    unittest.main()
