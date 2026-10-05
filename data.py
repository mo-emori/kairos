"""Minimal J-Quants V2 acquisition, as-of filtering, and raw archival."""

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "https://api.jquants.com/v2"
ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
PRICE_PATH = "/equities/bars/daily"
FINANCIAL_PATH = "/fins/summary"
LOGGER = logging.getLogger("jquants")

REQUIRED_FIELDS: tuple[str, ...] = (
    "ticker", "analysis_as_of", "data_as_of", "price", "revenue",
    "operating_profit", "net_income", "equity_ratio", "per",
)


def _load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"Configuration Error: cannot read {ENV_PATH.name}: {exc}") from exc
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    for key in ("JQUANTS_API_KEY", "DATA_ROOT"):
        if not values.get(key):
            raise ValueError(f"Configuration Error: {key} is not set in {ENV_PATH.name}")
    return values


def _request_all(path: str, code: str, api_key: str) -> dict[str, Any]:
    pages: list[dict[str, Any]] = []
    params = {"code": code}
    while True:
        url = f"{BASE_URL}{path}?{urlencode(params)}"
        request = Request(url, headers={"x-api-key": api_key, "Accept": "application/json"})
        try:
            with urlopen(request, timeout=30) as response:
                status = response.status
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace").replace(api_key, "[REDACTED]")[:500]
            raise ValueError(f"J-Quants API Error: {path} HTTP {exc.code}: {body}") from exc
        except (URLError, TimeoutError) as exc:
            detail = exc.reason if isinstance(exc, URLError) else exc
            raise ValueError(f"J-Quants API Error: {path}: {detail}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"J-Quants Data Error: {path} returned invalid JSON") from exc
        LOGGER.info("endpoint=%s status=%s", path, status)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ValueError(f"J-Quants Data Error: {path} response has no data list")
        pages.append(payload)
        pagination_key = payload.get("pagination_key")
        if not pagination_key:
            break
        params["pagination_key"] = str(pagination_key)
    return {"endpoint": path, "pages": pages}


def _records(raw: dict[str, Any]) -> list[dict[str, Any]]:
    return [record for page in raw["pages"] for record in page["data"] if isinstance(record, dict)]


def _number(value: Any) -> float | int | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _metric(current: float | int | None, prior: float | int | None) -> dict[str, Any]:
    change = current - prior if current is not None and prior is not None else None
    change_pct = change / prior if change is not None and prior is not None and prior > 0 else None
    return {"current": current, "prior_comparable": prior, "change": change, "change_pct": change_pct}


def _margin(record: dict[str, Any] | None, numerator: str) -> float | None:
    if not record:
        return None
    sales, value = _number(record.get("Sales")), _number(record.get(numerator))
    return value / sales if value is not None and sales not in (None, 0) else None


def _prior_comparable(current: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Match only the identical period type in the immediately prior fiscal year."""
    try:
        prior_year_end = date.fromisoformat(current["CurFYEn"]).replace(
            year=date.fromisoformat(current["CurFYEn"]).year - 1
        ).isoformat()
    except (KeyError, TypeError, ValueError):
        return None
    matches = [
        record for record in records
        if record.get("CurPerType") == current.get("CurPerType")
        and record.get("CurFYEn") == prior_year_end
    ]
    return max(matches, key=lambda r: (r.get("DiscDate") or "", r.get("DiscTime") or "", r.get("DiscNo") or ""), default=None)


def _historical(current: dict[str, Any], prior: dict[str, Any] | None) -> dict[str, Any]:
    fields = {"revenue": "Sales", "operating_profit": "OP", "net_income": "NP", "eps": "EPS",
              "equity_ratio": "EqAR"}
    result = {name: _metric(_number(current.get(field)), _number(prior.get(field)) if prior else None)
              for name, field in fields.items()}
    result["operating_margin"] = _metric(_margin(current, "OP"), _margin(prior, "OP"))
    result["net_margin"] = _metric(_margin(current, "NP"), _margin(prior, "NP"))
    return {
        "period_type": current.get("CurPerType") or None,
        "period_start": current.get("CurPerSt") or None,
        "period_end": current.get("CurPerEn") or None,
        "prior_period_start": prior.get("CurPerSt") if prior else None,
        "prior_period_end": prior.get("CurPerEn") if prior else None,
        "metrics": result,
    }


def _cash_flow(current: dict[str, Any]) -> dict[str, Any]:
    net_income, operating = _number(current.get("NP")), _number(current.get("CFO"))
    compatible = bool(current.get("CurPerSt") and current.get("CurPerEn"))
    return {
        "period_start": current.get("CurPerSt") or None, "period_end": current.get("CurPerEn") or None,
        "operating_cash_flow": operating, "investing_cash_flow": _number(current.get("CFI")),
        "financing_cash_flow": _number(current.get("CFF")),
        "cash_and_cash_equivalents": _number(current.get("CashEq")),
        "net_income": net_income if compatible else None,
        "operating_cash_flow_minus_net_income": operating - net_income
        if compatible and operating is not None and net_income is not None else None,
    }


def _forecast(current: dict[str, Any], price: float | int | None) -> dict[str, Any] | None:
    if current.get("CurPerType") == "FY" and current.get("NxtFYSt") and current.get("NxtFYEn"):
        prefix, np_field, period_start, period_end, dividend = (
            "NxF", "NxFNp", current["NxtFYSt"], current["NxtFYEn"], "NxFDivAnn"
        )
    elif current.get("CurFYSt") and current.get("CurFYEn"):
        prefix, np_field, period_start, period_end, dividend = (
            "F", "FNP", current["CurFYSt"], current["CurFYEn"], "FDivAnn"
        )
    else:
        return None
    eps = _number(current.get(prefix + "EPS"))
    values = {
        "revenue": _number(current.get(prefix + "Sales")),
        "operating_profit": _number(current.get(prefix + "OP")),
        "net_income": _number(current.get(np_field)), "eps": eps,
        "dividend_per_share": _number(current.get(dividend)),
    }
    if not any(value is not None for value in values.values()):
        return None
    return {
        "period_start": period_start, "period_end": period_end,
        "disclosure_date": current.get("DiscDate") or None, **values,
        "forward_per": price / eps if price is not None and eps is not None and eps > 0 else None,
    }


def _latest_relevant_forecast(
    current: dict[str, Any], records: list[dict[str, Any]], price: float | int | None,
) -> dict[str, Any] | None:
    """Select the latest disclosed forecast for the fiscal year relevant to the latest actual."""
    if current.get("CurPerType") == "FY":
        candidates = [record for record in records if record.get("NxtFYEn") == current.get("NxtFYEn")]
    else:
        candidates = [record for record in records if record.get("CurFYEn") == current.get("CurFYEn")]
    for record in reversed(candidates):
        forecast = _forecast(record, price)
        if forecast is not None:
            return forecast
    return None


def _price_trend(prices: list[dict[str, Any]]) -> dict[str, Any]:
    observations = [(record["Date"], _number(record.get("AdjC"))) for record in prices]
    observations = [(day, value) for day, value in observations if value is not None]
    current = observations[-1][1] if observations else None
    returns: dict[str, float | None] = {}
    for lookback, label in ((21, "21_observations"), (63, "63_observations"),
                            (126, "126_observations"), (252, "252_observations")):
        # N observations back means index -1-N, requiring N+1 adjusted-close observations.
        prior = observations[-1 - lookback][1] if len(observations) > lookback else None
        returns[label] = current / prior - 1 if current is not None and prior not in (None, 0) else None
    return {"price_date": observations[-1][0] if observations else None,
            "adjusted_close": current, "returns": returns}


def _archive(data_root: Path, ticker: str, run_label: str, name: str, payload: dict[str, Any]) -> Path:
    directory = data_root / "raw" / "jquants" / ticker / run_label
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def fetch_research_data(ticker: str, as_of: date | None = None) -> dict[str, Any]:
    """Fetch current API data, archive it, then build an as-of-safe research record."""
    env = _load_env()
    code = f"{ticker}0"
    prices_raw = _request_all(PRICE_PATH, code, env["JQUANTS_API_KEY"])
    financials_raw = _request_all(FINANCIAL_PATH, code, env["JQUANTS_API_KEY"])

    run_time = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    run_label = f"as-of-{as_of.isoformat()}-{run_time}" if as_of else f"run-{run_time}"
    price_raw_path = _archive(Path(env["DATA_ROOT"]), ticker, run_label, "prices", prices_raw)
    financial_raw_path = _archive(Path(env["DATA_ROOT"]), ticker, run_label, "financials", financials_raw)

    cutoff = as_of.isoformat() if as_of else None
    prices = [r for r in _records(prices_raw) if r.get("Date") and (cutoff is None or r["Date"] <= cutoff)]
    financials = [r for r in _records(financials_raw) if r.get("DiscDate") and (cutoff is None or r["DiscDate"] <= cutoff)]
    prices.sort(key=lambda r: r["Date"])
    financials.sort(key=lambda r: (r["DiscDate"], r.get("DiscTime") or "", r.get("DiscNo") or ""))
    price_record = next((r for r in reversed(prices) if _number(r.get("AdjC")) is not None), None)
    financial_record = next((r for r in reversed(financials) if any(_number(r.get(k)) is not None for k in ("Sales", "OP", "NP", "EPS", "EqAR"))), None)
    used_dates = [r[field] for r, field in ((price_record, "Date"), (financial_record, "DiscDate")) if r]
    if not used_dates:
        raise ValueError(f"J-Quants Data Error: no usable records for {ticker} at the requested as-of")
    analysis_date = cutoff or max(used_dates)
    price = _number(price_record.get("AdjC")) if price_record else None
    eps = _number(financial_record.get("EPS")) if financial_record else None
    per = price / eps if price is not None and eps not in (None, 0) else None
    prior = _prior_comparable(financial_record, financials) if financial_record else None
    latest_fy = next((r for r in reversed(financials) if r.get("CurPerType") == "FY" and _number(r.get("ROE")) is not None), None)
    company = {
        "snapshot": {"price": price,
                     "revenue": _number(financial_record.get("Sales")) if financial_record else None,
                     "operating_profit": _number(financial_record.get("OP")) if financial_record else None,
                     "net_income": _number(financial_record.get("NP")) if financial_record else None,
                     "equity_ratio": _number(financial_record.get("EqAR")) if financial_record else None,
                     "per": per},
        "historical_comparable": _historical(financial_record, prior) if financial_record else None,
        "roe": {"value": _number(latest_fy.get("ROE")), "period_end": latest_fy.get("CurPerEn")}
        if latest_fy else None,
        "cash_flow": _cash_flow(financial_record) if financial_record else None,
        "forecast": _latest_relevant_forecast(financial_record, financials, price) if financial_record else None,
        "price_trend": _price_trend(prices),
    }
    return {
        "source": "J-Quants API V2", "ticker": ticker,
        "company_name": "Unavailable (listed-company master not requested)", "analysis_as_of": analysis_date,
        "data_as_of": max(used_dates), "price": price,
        "revenue": _number(financial_record.get("Sales")) if financial_record else None,
        "operating_profit": _number(financial_record.get("OP")) if financial_record else None,
        "net_income": _number(financial_record.get("NP")) if financial_record else None,
        "equity_ratio": _number(financial_record.get("EqAR")) if financial_record else None,
        "per": per, "price_date": price_record.get("Date") if price_record else None,
        "financial_disclosure_date": financial_record.get("DiscDate") if financial_record else None,
        "company": company, "raw_paths": [str(price_raw_path), str(financial_raw_path)],
    }
