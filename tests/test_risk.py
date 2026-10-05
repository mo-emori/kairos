import unittest

from risk import evaluate_risk, is_held


RESEARCH = {
    "ticker": "7203", "analysis_as_of": "2026-10-05", "data_as_of": "2026-10-02",
    "price": 3000, "revenue": 100000, "operating_profit": 10000,
    "net_income": 7000, "equity_ratio": 40, "per": 12,
}


def assess(action="BUY", confidence="high", *, cash=500000, cash_ratio=0.5,
           holdings=None, research=None):
    portfolio = {"cash": cash, "cash_ratio": cash_ratio, "holdings": holdings or []}
    return evaluate_risk(action, confidence, research or RESEARCH, portfolio, 0.1, 0.2)


class RiskRulesTest(unittest.TestCase):
    def test_held_requires_positive_target_position_ratio(self):
        self.assertTrue(is_held({"holdings": [{"ticker": "7203", "position_ratio": 0.01}]}, "7203"))
        self.assertFalse(is_held({"holdings": [{"ticker": "7203", "position_ratio": 0.0}]}, "7203"))
        self.assertFalse(is_held({"holdings": []}, "7203"))

    def test_buy_high_and_medium_allocations(self):
        self.assertEqual(assess(confidence="high")["suggested_allocation"], 0.1)
        self.assertEqual(assess(confidence="medium")["suggested_allocation"], 0.05)

    def test_low_confidence_has_no_positive_allocation(self):
        result = assess(confidence="low")
        self.assertEqual(result["status"], "PASS")
        self.assertIsNone(result["suggested_allocation"])

    def test_add_is_capped_by_remaining_room_and_rejects_when_full(self):
        partial = assess("ADD", holdings=[{"ticker": "7203", "position_ratio": 0.08}])
        full = assess("ADD", holdings=[{"ticker": "7203", "position_ratio": 0.1}])
        self.assertAlmostEqual(partial["suggested_allocation"], 0.02)
        self.assertEqual(full["status"], "REJECT")
        self.assertIsNone(full["suggested_allocation"])

    def test_missing_required_data_rejects_buy_and_add(self):
        incomplete = dict(RESEARCH, price=None)
        for action in ("BUY", "ADD"):
            with self.subTest(action=action):
                self.assertEqual(assess(action, research=incomplete)["status"], "REJECT")

    def test_insufficient_cash_rejects(self):
        for cash, ratio in ((0, 0.5), (500000, 0.2)):
            with self.subTest(cash=cash, cash_ratio=ratio):
                result = assess(cash=cash, cash_ratio=ratio)
                self.assertEqual(result["status"], "REJECT")
                self.assertIsNone(result["suggested_allocation"])

    def test_negative_position_rejects(self):
        result = assess(holdings=[{"ticker": "9999", "position_ratio": -0.01}])
        self.assertEqual(result["status"], "REJECT")
        self.assertIsNone(result["suggested_allocation"])

    def test_non_buy_add_has_no_allocation(self):
        incomplete = dict(RESEARCH, price=None)
        for action in ("WATCH", "HOLD", "REDUCE", "SELL", "REJECT"):
            with self.subTest(action=action):
                result = assess(action, research=incomplete)
                self.assertEqual(result["status"], "PASS")
                self.assertIsNone(result["suggested_allocation"])


if __name__ == "__main__":
    unittest.main()
