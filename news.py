"""Minimal RSS 2.0 parsing and raw news JSONL storage."""

import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

RECORD_FIELDS: tuple[str, ...] = (
    "source", "published_at", "retrieved_at", "title", "summary", "url",
)


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
