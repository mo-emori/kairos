"""Minimal RSS storage and deterministic controlled-taxonomy matching."""

import json
import re
import unicodedata
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

RECORD_FIELDS: tuple[str, ...] = (
    "source", "published_at", "retrieved_at", "title", "summary", "url",
)
DEFAULT_TAXONOMY_PATH = Path(__file__).with_name("data") / "news_taxonomy.json"


def _non_empty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _keyword_dictionary(value: Any, name: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    for category_id, category in value.items():
        _non_empty_string(category_id, f"{name} ID")
        if not isinstance(category, dict) or set(category) != {"keywords"}:
            raise ValueError(f"{name}.{category_id} must contain only keywords")
        keywords = category["keywords"]
        if not isinstance(keywords, list) or not keywords:
            raise ValueError(f"{name}.{category_id}.keywords must be a non-empty list")
        for keyword in keywords:
            _non_empty_string(keyword, f"{name}.{category_id} keyword")


def validate_taxonomy(config: Any) -> dict[str, Any]:
    """Validate and return a Human-maintained news taxonomy object."""
    required = {"version", "sectors", "themes", "tickers"}
    if not isinstance(config, dict) or set(config) != required:
        raise ValueError("news taxonomy must contain version, sectors, themes, and tickers")
    if config["version"] != 1:
        raise ValueError("unsupported news taxonomy version")
    sectors = config["sectors"]
    if not isinstance(sectors, dict) or set(sectors) != {"sector_l1", "sector_l2"}:
        raise ValueError("sectors must contain sector_l1 and sector_l2")
    _keyword_dictionary(sectors["sector_l1"], "sector_l1")
    if not isinstance(sectors["sector_l2"], dict):
        raise ValueError("sector_l2 must be an object")
    for category_id, category in sectors["sector_l2"].items():
        _non_empty_string(category_id, "sector_l2 ID")
        if not isinstance(category, dict) or set(category) != {"sector_l1", "keywords"}:
            raise ValueError(f"sector_l2.{category_id} must contain sector_l1 and keywords")
        parent = _non_empty_string(category["sector_l1"], f"sector_l2.{category_id}.sector_l1")
        if parent not in sectors["sector_l1"]:
            raise ValueError(f"sector_l2.{category_id} references undefined sector_l1 {parent}")
        _keyword_dictionary({category_id: {"keywords": category["keywords"]}}, "sector_l2")
    _keyword_dictionary(config["themes"], "themes")
    if not isinstance(config["tickers"], dict):
        raise ValueError("tickers must be an object")
    ticker_fields = {"additional_aliases", "sector_l1", "sector_l2", "themes"}
    for ticker, mapping in config["tickers"].items():
        _non_empty_string(ticker, "ticker")
        if not isinstance(mapping, dict) or set(mapping) != ticker_fields:
            raise ValueError(f"ticker {ticker} must contain exactly {sorted(ticker_fields)}")
        aliases = mapping["additional_aliases"]
        if not isinstance(aliases, list):
            raise ValueError(f"ticker {ticker} additional_aliases must be a list")
        for alias in aliases:
            _non_empty_string(alias, f"ticker {ticker} additional alias")
        for layer in ("sector_l1", "sector_l2"):
            category_id = mapping[layer]
            if category_id is None:
                continue
            _non_empty_string(category_id, f"ticker {ticker} {layer}")
            if category_id not in sectors[layer]:
                raise ValueError(f"ticker {ticker} references undefined {layer} {category_id}")
        if mapping["sector_l2"] is not None and mapping["sector_l1"] is None:
            raise ValueError(f"ticker {ticker} sector_l2 requires sector_l1")
        if mapping["sector_l2"] is not None:
            parent = sectors["sector_l2"][mapping["sector_l2"]]["sector_l1"]
            if parent != mapping["sector_l1"]:
                raise ValueError(f"ticker {ticker} sector_l2 is not coherent with sector_l1")
        themes = mapping["themes"]
        if not isinstance(themes, list):
            raise ValueError(f"ticker {ticker} themes must be a list")
        for theme_id in themes:
            _non_empty_string(theme_id, f"ticker {ticker} theme")
            if theme_id not in config["themes"]:
                raise ValueError(f"ticker {ticker} references undefined theme {theme_id}")
    return config


def load_taxonomy(path: str | Path = DEFAULT_TAXONOMY_PATH) -> dict[str, Any]:
    """Load and validate the Human-editable news taxonomy JSON file."""
    try:
        with Path(path).open(encoding="utf-8") as config_file:
            config = json.load(config_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load news taxonomy: {path}") from exc
    return validate_taxonomy(config)


def _matching_keywords(text: str, keywords: list[str]) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    matches: list[str] = []
    for keyword in keywords:
        needle = unicodedata.normalize("NFKC", keyword).casefold()
        if needle.isascii() and any(character.isalnum() for character in needle):
            pattern = rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])"
            matched = re.search(pattern, normalized) is not None
        else:
            matched = needle in normalized
        if matched:
            matches.append(keyword)
    return matches


def match_news(
    record: dict[str, Any], ticker: str, company_identity: dict[str, Any] | None,
    taxonomy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Match one record using caller-supplied identity plus optional enrichment.

    ``company_identity`` is the compact data.py identity; ``name_ja`` and
    ``name_en`` are the only automatic aliases. An absent ticker enrichment is
    valid and simply disables Sector and Theme matching.
    """
    config = validate_taxonomy(taxonomy) if taxonomy is not None else load_taxonomy()
    ticker = str(ticker)
    title = record.get("title")
    summary = record.get("summary")
    if not isinstance(title, str) or not isinstance(summary, str):
        raise ValueError("news record title and summary must be strings")
    text = f"{title}\n{summary}"
    mapping = config["tickers"].get(ticker)
    result: dict[str, Any] = {}
    aliases = []
    if company_identity is not None:
        if not isinstance(company_identity, dict):
            raise ValueError("company_identity must be an object or null")
        for field in ("name_ja", "name_en"):
            value = company_identity.get(field)
            if isinstance(value, str) and value.strip() and value not in aliases:
                aliases.append(value)
    if mapping:
        aliases.extend(alias for alias in mapping["additional_aliases"] if alias not in aliases)
    company = _matching_keywords(text, aliases)
    if company:
        result["company"] = {"keywords": company}
    if not mapping:
        return result
    for layer in ("sector_l1", "sector_l2"):
        category_id = mapping[layer]
        if category_id is None:
            continue
        matched = _matching_keywords(text, config["sectors"][layer][category_id]["keywords"])
        if matched:
            result[layer] = {"id": category_id, "keywords": matched}
    theme_matches = []
    for theme_id in mapping["themes"]:
        matched = _matching_keywords(text, config["themes"][theme_id]["keywords"])
        if matched:
            theme_matches.append({"id": theme_id, "keywords": matched})
    if theme_matches:
        result["themes"] = theme_matches
    return result


def _utc_iso(value: datetime, name: str) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc).isoformat()


def _published_at(value: str) -> str | None:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def parse_rss(
    xml: bytes | str, source: str, retrieved_at: datetime,
) -> list[dict[str, str]]:
    """Parse the usable items from one supplied RSS 2.0 document.

    Items missing a title, link, or valid timezone-aware ``pubDate`` are
    skipped. A missing description is stored as an empty string. Invalid XML
    or a non-RSS-2.0 document raises ``ValueError``.
    """
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source must be a non-empty string")
    retrieved = _utc_iso(retrieved_at, "retrieved_at")
    try:
        root = ElementTree.fromstring(xml)
    except (ElementTree.ParseError, TypeError) as exc:
        raise ValueError("invalid RSS XML") from exc
    if root.tag != "rss" or root.get("version") != "2.0":
        raise ValueError("expected an RSS 2.0 document")
    channel = root.find("channel")
    if channel is None:
        raise ValueError("RSS 2.0 document is missing channel")

    records: list[dict[str, str]] = []
    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        published = _published_at((item.findtext("pubDate") or "").strip())
        if not title or not url or published is None:
            continue
        records.append({
            "source": source.strip(),
            "published_at": published,
            "retrieved_at": retrieved,
            "title": title,
            "summary": (item.findtext("description") or "").strip(),
            "url": url,
        })
    return records


def _stored_urls(raw_dir: Path) -> set[str]:
    urls: set[str] = set()
    for path in sorted(raw_dir.glob("*.jsonl")):
        with path.open(encoding="utf-8") as jsonl_file:
            for line_number, line in enumerate(jsonl_file, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    url = record["url"]
                except (json.JSONDecodeError, KeyError, TypeError) as exc:
                    raise ValueError(f"invalid news record in {path}:{line_number}") from exc
                if not isinstance(url, str) or not url:
                    raise ValueError(f"invalid news URL in {path}:{line_number}")
                urls.add(url)
    return urls


def store_news(records: list[dict[str, Any]], data_root: str | Path) -> list[dict[str, Any]]:
    """Append URL-unique records and return those written.

    The output date is the UTC calendar date of each record's aware ISO 8601
    ``retrieved_at`` value. Existing files for all dates are scanned so a URL
    is never re-added on a later collection day.
    """
    raw_dir = Path(data_root) / "news" / "raw"
    existing_urls = _stored_urls(raw_dir) if raw_dir.exists() else set()
    pending: list[tuple[Path, dict[str, Any]]] = []
    for record in records:
        if set(record) != set(RECORD_FIELDS):
            raise ValueError("news record must contain exactly the required fields")
        url = record["url"]
        if not isinstance(url, str) or not url:
            raise ValueError("news record URL must be a non-empty string")
        try:
            retrieved = datetime.fromisoformat(record["retrieved_at"])
        except (TypeError, ValueError) as exc:
            raise ValueError("news record retrieved_at must be an ISO 8601 datetime") from exc
        if retrieved.tzinfo is None or retrieved.utcoffset() is None:
            raise ValueError("news record retrieved_at must include a timezone")
        if url in existing_urls:
            continue
        existing_urls.add(url)
        day = retrieved.astimezone(timezone.utc).date().isoformat()
        pending.append((raw_dir / f"{day}.jsonl", record))

    for path, record in pending:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as jsonl_file:
            json.dump(record, jsonl_file, ensure_ascii=False, separators=(",", ":"))
            jsonl_file.write("\n")
    return [record for _, record in pending]
