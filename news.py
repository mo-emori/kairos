"""Minimal RSS storage and deterministic controlled-taxonomy matching."""

import json
import logging
import re
import time
import unicodedata
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from trafilatura import extract, fetch_url

RECORD_FIELDS: tuple[str, ...] = (
    "source", "published_at", "retrieved_at", "title", "summary", "url",
)
DEFAULT_TAXONOMY_PATH = Path(__file__).with_name("data") / "news_taxonomy.json"
DEFAULT_SOURCE_PATH = Path(__file__).with_name("data") / "news_sources.json"
SOURCE_FIELDS = {"source_id", "name", "url", "default_layer", "enabled"}
DEFAULT_LAYERS = {"market", "sector", "theme", "company"}
USER_AGENT = "KAIROS/0.3.1 RSS collector"
CONTENT_SUCCESS_FIELDS = {"url", "content_retrieved_at", "status", "text"}
CONTENT_FAILURE_FIELDS = {"url", "content_retrieved_at", "status", "error"}
MIN_CONTENT_CHARACTERS = 50
ENRICH_DELAY_SECONDS = 0.25
ANALYSIS_TIMEZONE = ZoneInfo("Asia/Tokyo")


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


def validate_sources(value: Any) -> list[dict[str, Any]]:
    """Validate and return the minimal Human-editable source registry."""
    if not isinstance(value, list):
        raise ValueError("news source registry must be a list")
    source_ids: set[str] = set()
    for index, source in enumerate(value):
        label = f"news source {index}"
        if not isinstance(source, dict) or set(source) != SOURCE_FIELDS:
            raise ValueError(f"{label} must contain exactly {sorted(SOURCE_FIELDS)}")
        source_id = _non_empty_string(source["source_id"], f"{label} source_id")
        if source_id in source_ids:
            raise ValueError(f"duplicate news source_id: {source_id}")
        source_ids.add(source_id)
        _non_empty_string(source["name"], f"{label} name")
        url = _non_empty_string(source["url"], f"{label} url")
        parsed_url = urlparse(url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError(f"{label} url must be an http/https URL")
        if source["default_layer"] not in DEFAULT_LAYERS:
            raise ValueError(f"{label} default_layer is not recognized")
        if not isinstance(source["enabled"], bool):
            raise ValueError(f"{label} enabled must be a boolean")
    return value


def load_sources(path: str | Path = DEFAULT_SOURCE_PATH) -> list[dict[str, Any]]:
    """Load and validate the Human-editable RSS source registry."""
    try:
        with Path(path).open(encoding="utf-8") as source_file:
            sources = json.load(source_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load news source registry: {path}") from exc
    return validate_sources(sources)


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
    taxonomy: dict[str, Any] | None = None, content_text: str | None = None,
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
    excerpt = content_excerpt(content_text) if content_text is not None else ""
    text = f"{title}\n{summary}" + (f"\n{excerpt}" if excerpt else "")
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


def fetch_source(
    source: dict[str, Any], retrieved_at: datetime, timeout: float = 15,
) -> list[dict[str, str]]:
    """Retrieve and parse one validated RSS source without following item links."""
    validate_sources([source])
    request = Request(source["url"], headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/xml, text/xml;q=0.9",
    })
    try:
        with urlopen(request, timeout=timeout) as response:
            xml = response.read()
    except HTTPError as exc:
        raise ValueError(
            f"News Feed Error: source={source['source_id']} HTTP {exc.code}"
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        detail = exc.reason if isinstance(exc, URLError) else exc
        raise ValueError(f"News Feed Error: source={source['source_id']}: {detail}") from exc
    try:
        return parse_rss(xml, source["name"], retrieved_at)
    except ValueError as exc:
        raise ValueError(f"News Feed Error: source={source['source_id']}: {exc}") from exc


def fetch_enabled_sources(
    sources: list[dict[str, Any]], retrieved_at: datetime,
) -> list[tuple[dict[str, Any], list[dict[str, str]]]]:
    """Fetch enabled sources in registry order; fail immediately on one source error."""
    validate_sources(sources)
    return [
        (source, fetch_source(source, retrieved_at))
        for source in sources if source["enabled"]
    ]


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


def _read_jsonl(path: Path, kind: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as jsonl_file:
        for line_number, line in enumerate(jsonl_file, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid {kind} JSON in {path}:{line_number}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"invalid {kind} record in {path}:{line_number}")
            records.append(record)
    return records


def load_raw_news(data_root: str | Path) -> list[dict[str, Any]]:
    """Load all stored Raw News records, preserving first-seen URL order."""
    raw_dir = Path(data_root) / "news" / "raw"
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(raw_dir.glob("*.jsonl")):
        for record in _read_jsonl(path, "raw news"):
            if set(record) != set(RECORD_FIELDS):
                raise ValueError(f"invalid raw news fields in {path}")
            url = record.get("url")
            if not isinstance(url, str) or not url:
                raise ValueError(f"invalid raw news URL in {path}")
            if url not in seen:
                seen.add(url)
                records.append(record)
    return records


def load_content_urls(data_root: str | Path) -> set[str]:
    """Scan and validate every content JSONL file, returning terminal URL identities."""
    return set(_load_content_news(data_root))


def _aware_timestamp(value: Any, name: str, path: Path) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {name} in {path}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"invalid {name} in {path}")
    return parsed.astimezone(timezone.utc)


def _load_content_news(data_root: str | Path) -> dict[str, dict[str, Any]]:
    """Load terminal Content observations keyed by their unique URL identity."""
    content_dir = Path(data_root) / "news" / "content"
    records: dict[str, dict[str, Any]] = {}
    for path in sorted(content_dir.glob("*.jsonl")):
        for record in _read_jsonl(path, "news content"):
            status = record.get("status")
            expected = CONTENT_SUCCESS_FIELDS if status == "success" else CONTENT_FAILURE_FIELDS
            if status not in {"success", "failed"} or set(record) != expected:
                raise ValueError(f"invalid news content fields in {path}")
            url = record.get("url")
            value_field = "text" if status == "success" else "error"
            if not isinstance(url, str) or not url or not isinstance(record.get(value_field), str) \
                    or not record[value_field]:
                raise ValueError(f"invalid news content record in {path}")
            _aware_timestamp(record.get("content_retrieved_at"), "news content timestamp", path)
            if url in records:
                raise ValueError(f"duplicate news content URL in {path}: {url}")
            records[url] = record
    return records


def analysis_cutoff(analysis_date: date) -> datetime:
    """Return the exclusive UTC cutoff at midnight after a Tokyo analysis date."""
    if not isinstance(analysis_date, date):
        raise ValueError("analysis_date must be a date")
    next_day = analysis_date + timedelta(days=1)
    return datetime.combine(next_day, datetime_time.min, tzinfo=ANALYSIS_TIMEZONE).astimezone(
        timezone.utc
    )


def select_news_context(
    data_root: str | Path, analysis_date: date, ticker: str,
    company_identity: dict[str, Any] | None, top_n_per_layer: int,
    *, sources: list[dict[str, Any]] | None = None,
    taxonomy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build deterministic, compact, as-of-safe News context from local stores only."""
    if not isinstance(top_n_per_layer, int) or isinstance(top_n_per_layer, bool) \
            or top_n_per_layer < 1:
        raise ValueError("news_top_n_per_layer must be a positive integer")
    source_registry = validate_sources(sources) if sources is not None else load_sources()
    source_layers = {source["name"]: source["default_layer"] for source in source_registry}
    taxonomy_config = validate_taxonomy(taxonomy) if taxonomy is not None else load_taxonomy()
    cutoff = analysis_cutoff(analysis_date)
    content_by_url = _load_content_news(data_root)
    candidates: dict[str, list[dict[str, Any]]] = {
        "market": [], "sector": [], "theme": [], "company": [],
    }

    for record in load_raw_news(data_root):
        raw_path = Path(data_root) / "news" / "raw"
        published = _aware_timestamp(record.get("published_at"), "published_at", raw_path)
        retrieved = _aware_timestamp(record.get("retrieved_at"), "retrieved_at", raw_path)
        if published >= cutoff or retrieved >= cutoff:
            continue
        content = content_by_url.get(record["url"])
        content_text = None
        if content is not None and content["status"] == "success":
            content_time = _aware_timestamp(
                content.get("content_retrieved_at"), "news content timestamp",
                Path(data_root) / "news" / "content",
            )
            if content_time < cutoff:
                content_text = content["text"]
        matches = match_news(
            record, ticker, company_identity, taxonomy_config, content_text=content_text,
        )
        categories: set[str] = set()
        default_layer = source_layers.get(record["source"])
        if default_layer in candidates:
            categories.add(default_layer)
        if "company" in matches:
            categories.add("company")
        if "sector_l1" in matches or "sector_l2" in matches:
            categories.add("sector")
        if "themes" in matches:
            categories.add("theme")
        if not categories:
            continue
        compact_matches: dict[str, Any] = {"layers": sorted(categories)}
        sectors = [
            {"level": layer, "id": matches[layer]["id"]}
            for layer in ("sector_l1", "sector_l2") if layer in matches
        ]
        if sectors:
            compact_matches["sectors"] = sectors
        if "themes" in matches:
            compact_matches["themes"] = [item["id"] for item in matches["themes"]]
        if "company" in matches:
            compact_matches["company"] = {"ticker": str(ticker)}
        item = {
            "source": record["source"],
            "published_at": record["published_at"],
            "title": record["title"],
            "excerpt": content_excerpt(content_text if content_text is not None else record["summary"]),
            "url": record["url"],
            "matches": compact_matches,
            "_published": published,
        }
        for category in categories:
            candidates[category].append(item)

    selected: dict[str, dict[str, Any]] = {}
    for category in ("market", "sector", "theme", "company"):
        ordered = sorted(
            candidates[category], key=lambda item: (-item["_published"].timestamp(), item["url"]),
        )
        for item in ordered[:top_n_per_layer]:
            selected[item["url"]] = item
    final = sorted(
        selected.values(), key=lambda item: (-item["_published"].timestamp(), item["url"]),
    )
    for item in final:
        del item["_published"]
    return final


def store_content(record: dict[str, Any], data_root: str | Path) -> Path:
    """Append one exact terminal content record to its UTC daily JSONL file."""
    status = record.get("status")
    expected = CONTENT_SUCCESS_FIELDS if status == "success" else CONTENT_FAILURE_FIELDS
    if status not in {"success", "failed"} or set(record) != expected:
        raise ValueError("news content record has invalid fields")
    value_field = "text" if status == "success" else "error"
    if not isinstance(record.get("url"), str) or not record["url"] \
            or not isinstance(record.get(value_field), str) or not record[value_field]:
        raise ValueError("news content record has invalid values")
    try:
        retrieved = datetime.fromisoformat(record["content_retrieved_at"])
    except (TypeError, ValueError) as exc:
        raise ValueError("content_retrieved_at must be an ISO 8601 datetime") from exc
    if retrieved.tzinfo is None or retrieved.utcoffset() is None:
        raise ValueError("content_retrieved_at must include a timezone")
    day = retrieved.astimezone(timezone.utc).date().isoformat()
    path = Path(data_root) / "news" / "content" / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as jsonl_file:
        json.dump(record, jsonl_file, ensure_ascii=False, separators=(",", ":"))
        jsonl_file.write("\n")
    return path


def normalize_content_text(text: str) -> str:
    """Apply only stable newline normalization and outer whitespace trimming."""
    if not isinstance(text, str):
        return ""
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def content_excerpt(text: str) -> str:
    """Return the deterministic first 600 Unicode characters of article text."""
    return normalize_content_text(text)[:600]


def retrieve_article_text(url: str) -> str:
    """Download normal HTML and extract its main text with Trafilatura."""
    downloaded = fetch_url(url)
    if not downloaded:
        raise ValueError("download returned no HTML")
    text = normalize_content_text(extract(downloaded) or "")
    if len(text) < MIN_CONTENT_CHARACTERS:
        raise ValueError("extracted text is empty or too short")
    return text


def enrich_news(
    data_root: str | Path, *, now: Any = None, sleep: Any = None,
) -> dict[str, int]:
    """Best-effort enrichment of unique, RSS-captured URLs not yet terminal."""
    records = load_raw_news(data_root)
    enriched = load_content_urls(data_root)
    pending = [record for record in records if record["url"] not in enriched]
    counts = {"processed": 0, "success": 0,
              "already_enriched": len(records) - len(pending), "failed": 0}
    clock = now if now is not None else (lambda: datetime.now(timezone.utc))
    sleeper = sleep if sleep is not None else time.sleep
    logger = logging.getLogger("news-enrich")
    for index, raw_record in enumerate(pending):
        if index:
            sleeper(ENRICH_DELAY_SECONDS)
        url = raw_record["url"]
        try:
            text = retrieve_article_text(url)
            status = "success"
        except Exception as exc:  # one article must never abort the batch
            status = "failed"
            if isinstance(exc, ValueError):
                error = str(exc)
            else:
                error = f"article retrieval raised {type(exc).__name__}"
            logger.warning("url=%s reason=%s", url, error)
        retrieved_at = clock()
        timestamp = _utc_iso(retrieved_at, "content_retrieved_at")
        record = {"url": url, "content_retrieved_at": timestamp, "status": status}
        if status == "success":
            record["text"] = text
        else:
            record["error"] = error
        store_content(record, data_root)
        counts["processed"] += 1
        counts[status] += 1
    return counts


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
