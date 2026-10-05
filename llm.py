"""Three OpenAI Responses API analysis calls for KAIROS."""

import json
import logging
from pathlib import Path
from typing import Any

from openai import OpenAI

ENV_PATH = Path(__file__).resolve().parent / ".env"
LOGGER = logging.getLogger("openai")

CONTEXT_GUIDANCE = (
    "Market context is a broad baseline, Sector context is an industry baseline, and Company context "
    "is company-specific evidence. Relative performance is descriptive and must not be treated as "
    "causal proof. null means unavailable and must never be treated as neutral or zero. "
)


def _client() -> OpenAI:
    """Build a client from the local UTF-8 .env without exposing its API key."""
    try:
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        raise ValueError("Model Error: cannot read local .env") from None
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    api_key = values.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("Model Error: OPENAI_API_KEY is not set in local .env")
    return OpenAI(api_key=api_key)


def _result(response: Any, call_name: str, model: str) -> dict[str, Any]:
    """Validate and decode one strict structured response."""
    usage = getattr(response, "usage", None)
    tokens = ""
    if usage is not None:
        tokens = " input_tokens=%s output_tokens=%s total_tokens=%s" % (
            getattr(usage, "input_tokens", "unknown"),
            getattr(usage, "output_tokens", "unknown"),
            getattr(usage, "total_tokens", "unknown"),
        )
    if getattr(response, "status", None) != "completed":
        LOGGER.error("call=%s model=%s success=false%s", call_name, model, tokens)
        raise ValueError(f"Model Error: {call_name} returned an incomplete response")
    for item in getattr(response, "output", []):
        for content in getattr(item, "content", []):
            if getattr(content, "type", None) == "refusal":
                LOGGER.error("call=%s model=%s success=false%s", call_name, model, tokens)
                raise ValueError(f"Model Error: {call_name} was refused")
    try:
        parsed = json.loads(response.output_text)
    except (TypeError, json.JSONDecodeError):
        LOGGER.error("call=%s model=%s success=false%s", call_name, model, tokens)
        raise ValueError(f"Model Error: {call_name} returned invalid structured output") from None
    if not isinstance(parsed, dict):
        LOGGER.error("call=%s model=%s success=false%s", call_name, model, tokens)
        raise ValueError(f"Model Error: {call_name} returned invalid structured output")
    LOGGER.info("call=%s model=%s success=true%s", call_name, model, tokens)
    return parsed


def positive_analysis(research_data: dict[str, Any], model: str) -> dict[str, Any]:
    """Call 1: fundamental, valuation, and bull analysis."""
    schema = {
        "type": "object",
        "properties": {
            "call": {"type": "string"}, "fundamental": {"type": "string"},
            "valuation": {"type": "string"}, "bull_case": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["call", "fundamental", "valuation", "bull_case", "evidence"],
        "additionalProperties": False,
    }
    prompt = (
        "Produce Call 1: concise Fundamental, Valuation, and Bull analysis with concise evidence. "
        "Use only the supplied J-Quants research_data. Do not use outside knowledge, training-memory "
        "facts about the company, future information, or unstated current market information. "
        "Treat analysis_as_of and data_as_of as strict time boundaries. " + CONTEXT_GUIDANCE + "research_data="
        + json.dumps(research_data, ensure_ascii=False)
    )
    try:
        response = _client().responses.create(
            model=model, input=prompt,
            text={"format": {"type": "json_schema", "name": "positive_analysis", "schema": schema, "strict": True}},
            store=False,
        )
    except Exception:
        LOGGER.error("call=call_1 model=%s success=false", model)
        raise ValueError("Model Error: Call 1 API request failed") from None
    return _result(response, "call_1", model)


def bear_risk_analysis(research_data: dict[str, Any], model: str) -> dict[str, Any]:
    """Call 2: independently assess bear factors using only base data."""
    schema = {
        "type": "object",
        "properties": {
            "call": {"type": "string"}, "bear_case": {"type": "string"},
            "risks": {"type": "array", "items": {"type": "string"}},
            "evidence": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["call", "bear_case", "risks", "evidence"],
        "additionalProperties": False,
    }
    prompt = (
        "Independently produce Call 2: concise Bear and Risk analysis with concise evidence. "
        "Use only the supplied J-Quants research_data; no Call 1 output, thesis, recommendation, or "
        "conclusions are available. Do not use outside knowledge, training-memory facts about the company, "
        "future information, or unstated current market information. Treat analysis_as_of and data_as_of "
        "as strict time boundaries. " + CONTEXT_GUIDANCE + "research_data="
        + json.dumps(research_data, ensure_ascii=False)
    )
    try:
        response = _client().responses.create(
            model=model, input=prompt,
            text={"format": {"type": "json_schema", "name": "bear_risk_analysis", "schema": schema, "strict": True}},
            store=False,
        )
    except Exception:
        LOGGER.error("call=call_2 model=%s success=false", model)
        raise ValueError("Model Error: Call 2 API request failed") from None
    return _result(response, "call_2", model)


def synthesize_analysis(
    research_data: dict[str, Any], call_1: dict[str, Any], call_2: dict[str, Any], held: bool, model: str,
) -> dict[str, Any]:
    """Call 3: synthesize base data and both independent analyses."""
    recommendations = ["ADD", "HOLD", "REDUCE", "SELL"] if held else ["BUY", "WATCH", "AVOID"]
    schema = {
        "type": "object",
        "properties": {
            "call": {"type": "string"},
            "contradictions": {"type": "array", "items": {"type": "string"}},
            "unresolved_questions": {"type": "array", "items": {"type": "string"}},
            "thesis": {"type": "string"},
            "invalidators": {"type": "array", "items": {"type": "string"}},
            "expected_events": {"type": "array", "items": {"type": "string"}},
            "recommendation": {"type": "string", "enum": recommendations},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "primary_reason": {"type": "string"}, "strongest_counterargument": {"type": "string"},
            "base_data_identity": {"type": "string"},
        },
        "required": [
            "call", "contradictions", "unresolved_questions", "thesis", "invalidators",
            "expected_events", "recommendation", "confidence", "primary_reason",
            "strongest_counterargument", "base_data_identity",
        ],
        "additionalProperties": False,
    }
    payload = {
        "research_data": research_data, "call_1": call_1, "call_2": call_2,
        "holding_status": "held" if held else "not_held",
    }
    prompt = (
        "Produce Call 3 synthesis. Keep Bull and Bear distinct; explicitly report contradictions and "
        "unresolved questions, then thesis, invalidators, expected events, recommendation, confidence, "
        "primary reason, strongest counterargument, and base-data identity. WATCH means investment interest "
        "is positive but evidence or three-month risk/reward is insufficient to initiate. AVOID means "
        "three-month risk/reward does not support initiating. Use only the supplied payload. "
        "Do not use outside knowledge, training-memory facts about the company, future information, or "
        "unstated current market information. Treat analysis_as_of and data_as_of as strict time boundaries. "
        + CONTEXT_GUIDANCE +
        "payload=" + json.dumps(payload, ensure_ascii=False)
    )
    try:
        response = _client().responses.create(
            model=model, input=prompt,
            text={"format": {"type": "json_schema", "name": "synthesize_analysis", "schema": schema, "strict": True}},
            store=False,
        )
    except Exception:
        LOGGER.error("call=call_3 model=%s success=false", model)
        raise ValueError("Model Error: Call 3 API request failed") from None
    return _result(response, "call_3", model)
