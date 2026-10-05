import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import llm


class LlmContextAndSchemaTest(unittest.TestCase):
    def test_call_1_and_2_share_only_base_context(self):
        inputs = []

        class Responses:
            def create(self, **kwargs):
                inputs.append(kwargs["input"])
                name = kwargs["text"]["format"]["name"]
                output = ({"call": "1", "fundamental": "f", "valuation": "v", "bull_case": "b",
                           "evidence": []} if name == "positive_analysis" else
                          {"call": "2", "bear_case": "b", "risks": [], "evidence": []})
                return SimpleNamespace(status="completed", output=[], output_text=json.dumps(output), usage=None)

        context = {"ticker": "7203", "analysis_as_of": "2026-10-05",
                   "data_as_of": "2026-10-02", "investment_horizon": "3 months",
                   "company": {"forecast": {"eps": None}}}
        with patch.object(llm, "_client", return_value=SimpleNamespace(responses=Responses())):
            call_1 = llm.positive_analysis(context, "model")
            llm.bear_risk_analysis(context, "model")
        for prompt in inputs:
            self.assertIn(json.dumps(context, ensure_ascii=False), prompt)
            self.assertNotIn("holding_status", prompt)
            self.assertNotIn("portfolio", prompt)
        self.assertNotIn(json.dumps(call_1), inputs[1])
        self.assertIn("null means unavailable", inputs[0])
        self.assertIn("null means unavailable", inputs[1])
        for prompt in inputs:
            self.assertIn("Market context is a broad baseline", prompt)
            self.assertIn("Sector context is an industry baseline", prompt)
            self.assertIn("Company context is company-specific evidence", prompt)
            self.assertIn("must not be treated as causal proof", prompt)

    def _capture_synthesis(self, held):
        captured = {}

        class Responses:
            def create(self, **kwargs):
                captured.update(kwargs)
                recommendation = "HOLD" if held else "WATCH"
                output = {
                    "call": "3", "contradictions": [], "unresolved_questions": [], "thesis": "t",
                    "invalidators": [], "expected_events": [], "recommendation": recommendation,
                    "confidence": "medium", "primary_reason": "p", "strongest_counterargument": "c",
                    "base_data_identity": "b",
                }
                return SimpleNamespace(status="completed", output=[], output_text=json.dumps(output), usage=None)

        client = SimpleNamespace(responses=Responses())
        context = {"ticker": "7203", "analysis_as_of": "2026-10-05",
                   "data_as_of": "2026-10-02", "investment_horizon": "3 months"}
        with patch.object(llm, "_client", return_value=client):
            llm.synthesize_analysis(context, {"call": "1"}, {"call": "2"}, held, "model")
        return captured

    def test_not_held_schema_and_payload(self):
        captured = self._capture_synthesis(False)
        schema = captured["text"]["format"]["schema"]
        self.assertEqual(schema["properties"]["recommendation"]["enum"], ["BUY", "WATCH", "AVOID"])
        self.assertNotIn("REJECT", json.dumps(schema))
        payload = json.loads(captured["input"].split("payload=", 1)[1])
        self.assertEqual(payload["holding_status"], "not_held")
        self.assertNotIn("portfolio", payload)
        self.assertEqual(set(payload), {"research_data", "call_1", "call_2", "holding_status"})

    def test_held_schema_and_payload(self):
        captured = self._capture_synthesis(True)
        schema = captured["text"]["format"]["schema"]
        self.assertEqual(schema["properties"]["recommendation"]["enum"], ["ADD", "HOLD", "REDUCE", "SELL"])
        self.assertNotIn("REJECT", json.dumps(schema))
        payload = json.loads(captured["input"].split("payload=", 1)[1])
        self.assertEqual(payload["holding_status"], "held")


if __name__ == "__main__":
    unittest.main()
